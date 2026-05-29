import json
import os
import time
import requests
from datetime import datetime

from config.keywords import KEYWORDS

OUTPUT_PATH = "data/raw/scraped_reddit.json"

# Öffentliche Reddit JSON Endpoints — kein API Key nötig
SUBREDDITS = [
    "germany",
    "LegalAdviceGerman",
    "Eltern",
    "de"
]

HEADERS = {
    # Reddit blockiert ohne User-Agent
    "User-Agent": "Mozilla/5.0 (compatible; ServiceSonar/1.0)"
}

# Wartezeit zwischen Requests — Reddit Rate Limiting respektieren
CRAWL_DELAY = 2

# ── CONTENT FILTER KONFIGURATION ──────────────────────────────────────────────
MIN_WORDS = 20      # Reddit Posts können kurz sein — niedriger als Web Scraper
MAX_WORDS = 10000   # Reddit Posts selten länger
# ──────────────────────────────────────────────────────────────────────────────


def search_subreddit(subreddit: str, keyword: str, limit: int = 25) -> list:
    """
    Sucht in einem Subreddit nach einem Keyword via öffentlichem JSON Endpoint.
    Gibt Liste von Posts zurück.
    """
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": keyword,
        "limit": limit,
        "restrict_sr": 1,   # nur innerhalb des Subreddits suchen
        "sort": "relevance"
    }

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("children", [])
    except Exception as e:
        print(f"Fehler bei r/{subreddit} '{keyword}': {e}")
        return []


def is_valid_content(text: str) -> tuple[bool, str]:
    """
    ── CONTENT FILTER (Content-Level) ──
    Prüft ob Post verwertbar ist anhand der Wortanzahl.
    """
    word_count = len(text.split())
    if word_count < MIN_WORDS:
        return False, f"zu kurz ({word_count} Wörter)"
    if word_count > MAX_WORDS:
        return False, f"zu lang ({word_count} Wörter)"
    return True, "ok"


def parse_post(post: dict) -> dict | None:
    """
    Extrahiert relevante Felder aus einem Reddit Post.
    Kombiniert Titel + Selftext für maximalen Textinhalt.
    """
    data = post.get("data", {})

    title = data.get("title", "")
    selftext = data.get("selftext", "")

    # Titel + Text kombinieren für Analyse
    full_text = f"{title} {selftext}".strip()

    # ── CONTENT FILTER anwenden ──
    valid, reason = is_valid_content(full_text)
    if not valid:
        return None
    # ────────────────────────────

    return {
        "url": f"https://www.reddit.com{data.get('permalink', '')}",
        "title": title,
        "text": full_text,
        "subreddit": data.get("subreddit", ""),
        "score": data.get("score", 0),          # Upvotes als Relevanz-Signal
        "num_comments": data.get("num_comments", 0),
        "date": datetime.fromtimestamp(data.get("created_utc", 0)).isoformat(),
        "scraped_at": datetime.now().isoformat(),
        "source": "reddit"
    }


def run():
    """
    Einstiegspunkt — durchsucht alle Subreddits mit allen Keywords
    und speichert verwertbare Posts in scraped_reddit.json.
    """
    print("Reddit Scraper gestartet...")

    results = []
    seen_urls = set()  # Duplikate vermeiden

    for subreddit in SUBREDDITS:
        for keyword in KEYWORDS:
            print(f"r/{subreddit} → '{keyword}'")

            posts = search_subreddit(subreddit, keyword)

            for post in posts:
                parsed = parse_post(post)
                if not parsed:
                    continue

                # Duplikate überspringen
                if parsed["url"] in seen_urls:
                    continue

                seen_urls.add(parsed["url"])
                results.append(parsed)

            # Rate Limiting respektieren
            time.sleep(CRAWL_DELAY)

    os.makedirs("data/raw", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"{len(results)} Posts gescrapt → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()