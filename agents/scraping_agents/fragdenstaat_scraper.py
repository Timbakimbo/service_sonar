import json
import os
import time
import requests
from datetime import datetime

OUTPUT_PATH = "data/raw/scraped_fragdenstaat.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ServiceSonar/1.0)"
}

# Behörden die wir abfragen
BEHOERDEN = {
    "ZBFS": 12904,
    "Familienkasse_Bayern_Nord": 14032,
    "StMAS_Bayern_Familie": 11209
}

CRAWL_DELAY = 1

# ── CONTENT FILTER ─────────────────────────────────────────────────────────────
MIN_WORDS = 3
# ──────────────────────────────────────────────────────────────────────────────


def fetch_requests(behoerde_id: int, offset: int = 0) -> dict:
    """
    Holt eine Seite von Anfragen für eine Behörde via FragdenStaat API.
    """
    url = "https://fragdenstaat.de/api/v1/request/"
    params = {
        "public_body": behoerde_id,
        "format": "json",
        "limit": 50,
        "offset": offset
    }
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Fehler bei Behörde {behoerde_id} (offset {offset}): {e}")
        return {}


def fetch_messages(request_id: int) -> list:
    """
    Holt Nachrichten (Anfragetext + Behördenantwort) für eine Anfrage.
    """
    url = f"https://fragdenstaat.de/api/v1/message/?request={request_id}&format=json"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.json().get("objects", [])
    except Exception as e:
        print(f"Fehler bei Messages für Request {request_id}: {e}")
        return []


def parse_request(req: dict, behoerde_name: str) -> dict | None:
    """
    Extrahiert relevante Felder aus einer FragdenStaat Anfrage.
    Nutzt description + summary direkt aus dem Request Objekt.
    """
    title = req.get("title", "")
    description = req.get("description", "") or req.get("redacted_description", "")
    summary = req.get("summary", "")

    full_text = f"{title} {description} {summary}".strip()

    # ── CONTENT FILTER ──
    if len(full_text.split()) < MIN_WORDS:
        return None
    # ───────────────────

    return {
        "url": req.get("url", ""),
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
        "source": "fragdenstaat"
    }


def scrape_behoerde(behoerde_name: str, behoerde_id: int, existing_urls: set) -> list:
    """
    Scrapt alle Anfragen für eine Behörde — überspringt bekannte URLs.
    """
    results = []
    offset = 0

    print(f"Scrape {behoerde_name} (ID: {behoerde_id})...")

    while True:
        data = fetch_requests(behoerde_id, offset)
        objects = data.get("objects", [])

        if not objects:
            break

        for req in objects:
            url = f"https://fragdenstaat.de/anfrage/{req.get('slug', '')}"

            # Duplikat überspringen
            if url in existing_urls:
                print(f"  Übersprungen (bereits vorhanden): {req.get('title', '')[:50]}")
                continue

            print(f"  [{offset + objects.index(req) + 1}] {req.get('title', '')[:60]}")
            parsed = parse_request(req, behoerde_name)
            if parsed:
                results.append(parsed)
                existing_urls.add(url)  # direkt zum Cache hinzufügen
            time.sleep(CRAWL_DELAY)

        # Nächste Seite
        if not data.get("meta", {}).get("next"):
            break
        offset += 50

    return results


def run():
    """
    Einstiegspunkt — lädt bestehende Daten, scrapt nur neue Anfragen.
    """
    print("FragdenStaat Scraper gestartet...")

    # Bestehende Daten laden
    existing_urls = set()
    existing_results = []
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            existing_results = json.load(f)
            existing_urls = {r["url"] for r in existing_results}
        print(f"{len(existing_results)} bestehende Anfragen geladen")

    new_results = []
    for behoerde_name, behoerde_id in BEHOERDEN.items():
        results = scrape_behoerde(behoerde_name, behoerde_id, existing_urls)
        new_results.extend(results)
        print(f"  → {len(results)} neue Anfragen")

    all_results = existing_results + new_results

    os.makedirs("data/raw", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{len(new_results)} neue + {len(existing_results)} bestehende = {len(all_results)} gesamt → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()