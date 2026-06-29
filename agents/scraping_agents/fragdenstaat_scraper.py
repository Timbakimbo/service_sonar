import json
import os
import time
from datetime import datetime
from urllib.parse import urljoin

import requests

from scripts.save_metrics import save_fragdenstaat_metrics

OUTPUT_PATH = "data/raw/scraped_fragdenstaat.json"
BASE_URL = "https://fragdenstaat.de"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ServiceSonar/1.0)"
}

BEHOERDEN = {
    "ZBFS": 12904,
    "Familienkasse_Bayern_Nord": 14032,
    "StMAS_Bayern_Familie": 11209,
}

CRAWL_DELAY = 1
MIN_WORDS = 3


def normalize_request_url(url: str) -> str:
    """Return a stable absolute FragDenStaat request URL."""
    if not url:
        return ""
    normalized = urljoin(BASE_URL, url)
    return normalized if normalized.endswith("/") else f"{normalized}/"


def request_identifiers(record: dict) -> set[str]:
    """Return all stable identifiers known for a request."""
    identifiers = set()
    request_id = record.get("request_id") or record.get("id")
    if request_id:
        identifiers.add(f"id:{request_id}")
    normalized_url = normalize_request_url(record.get("url", ""))
    if normalized_url:
        identifiers.add(f"url:{normalized_url}")
    return identifiers


def request_identifier(record: dict) -> str:
    """Return a primary stable identifier for metrics/debugging."""
    identifiers = sorted(request_identifiers(record))
    return identifiers[0] if identifiers else "missing:"


def deduplicate_records(records: list[dict]) -> tuple[list[dict], int]:
    """Deduplicate existing records by stable request id or normalized URL."""
    deduped = []
    seen = set()
    duplicate_count = 0

    for record in records:
        record = dict(record)
        record["url"] = normalize_request_url(record.get("url", ""))
        identifiers = request_identifiers(record)
        if seen.intersection(identifiers):
            duplicate_count += 1
            continue
        seen.update(identifiers)
        deduped.append(record)

    return deduped, duplicate_count


def fetch_requests(behoerde_id: int, offset: int = 0) -> dict:
    """Fetch one page of public requests for an authority."""
    url = f"{BASE_URL}/api/v1/request/"
    params = {
        "public_body": behoerde_id,
        "format": "json",
        "limit": 50,
        "offset": offset,
    }
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(f"Fehler bei Behoerde {behoerde_id} (offset {offset}): {exc}")
        return {}


def fetch_messages(request_id: int) -> list:
    """
    Fetch messages for a request.

    Kept for later OAuth-based work. The public endpoint currently returns no useful
    message bodies for this prototype, so parse_request uses description/summary.
    """
    url = f"{BASE_URL}/api/v1/message/?request={request_id}&format=json"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.json().get("objects", [])
    except Exception as exc:
        print(f"Fehler bei Messages fuer Request {request_id}: {exc}")
        return []


def request_url_from_api_object(req: dict) -> str:
    if req.get("url"):
        return normalize_request_url(req.get("url", ""))
    slug = req.get("slug", "")
    return normalize_request_url(f"/anfrage/{slug}/")


def parse_request(req: dict, behoerde_name: str) -> dict | None:
    """Extract relevant fields from a FragDenStaat request object."""
    title = req.get("title", "")
    description = req.get("description", "") or req.get("redacted_description", "")
    summary = req.get("summary", "")
    full_text = f"{title} {description} {summary}".strip()

    if len(full_text.split()) < MIN_WORDS:
        return None

    return {
        "request_id": req.get("id"),
        "url": request_url_from_api_object(req),
        "title": title,
        "text": full_text,
        "anfrage_text": description,
        "antwort_text": summary,
        "status": req.get("status", ""),
        "refusal_reason": req.get("refusal_reason", ""),
        "law": req.get("law", ""),
        "behoerde": behoerde_name,
        "date": req.get("created_at", ""),
        "scraped_at": datetime.now().isoformat(),
        "source": "fragdenstaat",
    }


def scrape_behoerde(
    behoerde_name: str,
    behoerde_id: int,
    existing_identifiers: set[str],
) -> list:
    """Scrape all public requests for one authority, skipping known records."""
    results = []
    offset = 0

    print(f"Scrape {behoerde_name} (ID: {behoerde_id})...")

    while True:
        data = fetch_requests(behoerde_id, offset)
        objects = data.get("objects", [])
        if not objects:
            break

        for index, req in enumerate(objects, start=1):
            probe = {
                "request_id": req.get("id"),
                "url": request_url_from_api_object(req),
            }
            identifiers = request_identifiers(probe)
            if existing_identifiers.intersection(identifiers):
                print(f"  Uebersprungen (bereits vorhanden): {req.get('title', '')[:50]}")
                continue

            print(f"  [{offset + index}] {req.get('title', '')[:60]}")
            parsed = parse_request(req, behoerde_name)
            if parsed:
                results.append(parsed)
                existing_identifiers.update(request_identifiers(parsed))
            time.sleep(CRAWL_DELAY)

        if not data.get("meta", {}).get("next"):
            break
        offset += 50

    return results


def run():
    """Load existing data, scrape only new requests, save metrics."""
    print("FragDenStaat Scraper gestartet...")

    existing_raw = []
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            existing_raw = json.load(f)
        print(f"{len(existing_raw)} bestehende Anfragen geladen")

    existing_results, duplicate_count = deduplicate_records(existing_raw)
    if duplicate_count:
        print(f"{duplicate_count} doppelte bestehende Anfragen beim Laden entfernt")

    existing_identifiers = set()
    for record in existing_results:
        existing_identifiers.update(request_identifiers(record))
    new_results = []

    for behoerde_name, behoerde_id in BEHOERDEN.items():
        results = scrape_behoerde(behoerde_name, behoerde_id, existing_identifiers)
        new_results.extend(results)
        print(f"  -> {len(results)} neue Anfragen")

    all_results, final_duplicate_count = deduplicate_records(existing_results + new_results)
    duplicate_count += final_duplicate_count

    os.makedirs("data/raw", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    run_stats = {
        "authorities_checked": len(BEHOERDEN),
        "existing_count_before_run": len(existing_raw),
        "new_count": len(new_results),
        "total_count_after_run": len(all_results),
        "duplicate_count": duplicate_count,
    }
    saved_metrics = save_fragdenstaat_metrics("fragdenstaat_scraper_run", run_stats)

    print(
        f"\n{len(new_results)} neue + {len(existing_results)} bestehende "
        f"= {len(all_results)} gesamt -> {OUTPUT_PATH}"
    )
    print(
        "Metrics gespeichert -> data/metrics.json "
        f"({saved_metrics['duplicate_count']} Duplikate erkannt)"
    )


if __name__ == "__main__":
    run()
