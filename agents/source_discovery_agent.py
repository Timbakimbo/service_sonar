import json
import os
from ddgs import DDGS
from config.keywords import KEYWORDS

# Output-Pfad für gefundene Sources
OUTPUT_PATH = "data/raw/sources.json"

# ── CONTENT FILTER KONFIGURATION ──────────────────────────────────────────────
BLACKLISTED_DOMAINS = [
    "tiktok.com", "instagram.com", "facebook.com",
    "huggingface.co", "twitter.com", "youtube.com"
]

BLACKLISTED_URL_PATTERNS = [
    ".pdf", "/impressum", "/datenschutz",
    "/kontakt", "/cookie", "/agb", "/sitemap"
]
# ──────────────────────────────────────────────────────────────────────────────


def is_valid_url(url: str) -> bool:
    """
    ── CONTENT FILTER (URL-Level) ──
    Gibt False zurück wenn URL auf Blacklisted Domain
    oder Blacklisted Pattern zeigt.
    """
    url_lower = url.lower()
    for domain in BLACKLISTED_DOMAINS:
        if domain in url_lower:
            return False
    for pattern in BLACKLISTED_URL_PATTERNS:
        if pattern in url_lower:
            return False
    return True


def search_ddg(query: str, num_results: int = 10) -> list:
    """Sucht via DuckDuckGo, gibt URLs + Quelle zurück."""
    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=num_results)
            return [
                {"url": r["href"], "source": "duckduckgo"}
                for r in results
            ]
    except Exception as e:
        print(f"DDG fehlgeschlagen für '{query}': {e}")
        return []


def discover_sources() -> tuple[list, dict]:
    """
    Iteriert über Keywords, sucht via DDG,
    filtert Duplikate und ungültige URLs.
    Gibt Sources + Filter-Stats zurück.
    """
    all_sources = []
    seen_urls = set()
    stats = {"total_found": 0, "filtered": 0, "accepted": 0}

    for keyword in KEYWORDS:
        print(f"Suche nach: {keyword}")
        results = search_ddg(keyword)
        stats["total_found"] += len(results)

        for result in results:
            url = result["url"]

            if url in seen_urls:
                continue

            # ── CONTENT FILTER anwenden ──
            if not is_valid_url(url):
                print(f"  Gefiltert: {url}")
                stats["filtered"] += 1
                continue
            # ────────────────────────────

            seen_urls.add(url)
            all_sources.append(result)
            stats["accepted"] += 1

    stats["filter_rate_pct"] = round(
        stats["filtered"] / stats["total_found"] * 100, 1
    ) if stats["total_found"] else 0

    return all_sources, stats


def run():
    """Einstiegspunkt — startet Discovery und speichert Output."""
    print("Source Discovery gestartet ...")
    sources, stats = discover_sources()

    os.makedirs("data/raw", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)

    print(f"\n── Filter Stats ──")
    print(f"  Gefunden:  {stats['total_found']}")
    print(f"  Gefiltert: {stats['filtered']} ({stats['filter_rate_pct']}%)")
    print(f"  Akzeptiert: {stats['accepted']}")
    print(f"\n{len(sources)} Sources gespeichert → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()