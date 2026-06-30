import json
import os
import time
from datetime import datetime

import requests

from config.keywords import KEYWORDS
from scripts.save_metrics import save_reddit_metrics

OUTPUT_PATH = "data/raw/scraped_reddit.json"
PARTIAL_OUTPUT_PATH = "data/raw/scraped_reddit_partial.json"

# Public Reddit JSON endpoints, no API key.
SUBREDDITS = [
    "germany",
    "LegalAdviceGerman",
    "Eltern",
    "de",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ServiceSonar/1.0)"
}

CRAWL_DELAY = 2
MIN_WORDS = 20
MAX_WORDS = 10000


def init_metrics() -> dict:
    return {
        "attempted_subreddits": len(SUBREDDITS),
        "attempted_queries": len(KEYWORDS),
        "attempted_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "blocked_403_count": 0,
        "collected_posts": 0,
        "saved_posts": 0,
        "filtered_too_short": 0,
        "filtered_too_long": 0,
        "interrupted": False,
        "existing_data_preserved": False,
        "partial_posts_collected": 0,
        "partial_output_path": "",
        "preserve_reason": "",
    }


def search_subreddit(subreddit: str, keyword: str, metrics: dict, limit: int = 25) -> list:
    """Search one subreddit via Reddit's public JSON endpoint."""
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": keyword,
        "limit": limit,
        "restrict_sr": 1,
        "sort": "relevance",
    }

    metrics["attempted_requests"] += 1
    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError as exc:
        metrics["failed_requests"] += 1
        status_code = getattr(exc.response, "status_code", None)
        if status_code == 403:
            metrics["blocked_403_count"] += 1
        print(f"Fehler bei r/{subreddit} '{keyword}': {exc}")
        return []
    except Exception as exc:
        metrics["failed_requests"] += 1
        print(f"Fehler bei r/{subreddit} '{keyword}': {exc}")
        return []

    children = data.get("data", {}).get("children", [])
    metrics["successful_requests"] += 1
    metrics["collected_posts"] += len(children)
    return children


def is_valid_content(text: str) -> tuple[bool, str]:
    """Filter Reddit posts by word count."""
    word_count = len(text.split())
    if word_count < MIN_WORDS:
        return False, "too_short"
    if word_count > MAX_WORDS:
        return False, "too_long"
    return True, "ok"


def parse_post(post: dict, metrics: dict) -> dict | None:
    """Extract relevant fields from a Reddit post."""
    data = post.get("data", {})
    title = data.get("title", "")
    selftext = data.get("selftext", "")
    full_text = f"{title} {selftext}".strip()

    valid, reason = is_valid_content(full_text)
    if not valid:
        if reason == "too_short":
            metrics["filtered_too_short"] += 1
        elif reason == "too_long":
            metrics["filtered_too_long"] += 1
        return None

    return {
        "url": f"https://www.reddit.com{data.get('permalink', '')}",
        "title": title,
        "text": full_text,
        "subreddit": data.get("subreddit", ""),
        "score": data.get("score", 0),
        "num_comments": data.get("num_comments", 0),
        "date": datetime.fromtimestamp(data.get("created_utc", 0)).isoformat(),
        "scraped_at": datetime.now().isoformat(),
        "source": "reddit",
    }


def should_preserve_existing_file(metrics: dict, mostly_blocked: bool) -> bool:
    no_successful_requests = (
        metrics["attempted_requests"] > 0
        and metrics["successful_requests"] == 0
    )
    return (
        os.path.exists(OUTPUT_PATH)
        and (metrics["interrupted"] or no_successful_requests or mostly_blocked)
    )


def preserve_reason(metrics: dict, mostly_blocked: bool) -> str:
    if metrics["interrupted"]:
        return "interrupted"
    if metrics["attempted_requests"] > 0 and metrics["successful_requests"] == 0:
        return "all_requests_failed"
    if mostly_blocked:
        return "mostly_blocked"
    return ""


def run():
    """Search all configured subreddits and save usable posts plus metrics."""
    print("Reddit Scraper gestartet...")

    results = []
    seen_urls = set()
    metrics = init_metrics()

    try:
        for subreddit in SUBREDDITS:
            for keyword in KEYWORDS:
                print(f"r/{subreddit} -> '{keyword}'")
                posts = search_subreddit(subreddit, keyword, metrics)

                for post in posts:
                    parsed = parse_post(post, metrics)
                    if not parsed or parsed["url"] in seen_urls:
                        continue
                    seen_urls.add(parsed["url"])
                    results.append(parsed)

                time.sleep(CRAWL_DELAY)
    except KeyboardInterrupt:
        metrics["interrupted"] = True
        print("\nReddit Scraper manuell unterbrochen.")

    mostly_blocked = (
        metrics["attempted_requests"] > 0
        and metrics["blocked_403_count"] / metrics["attempted_requests"] >= 0.8
    )

    if should_preserve_existing_file(metrics, mostly_blocked):
        metrics["existing_data_preserved"] = True
        metrics["partial_posts_collected"] = len(results)
        metrics["preserve_reason"] = preserve_reason(metrics, mostly_blocked)
        print(
            f"{len(results)} Posts gesammelt. Bestehende {OUTPUT_PATH} bleibt erhalten, "
            "damit Downstream-Tests nicht durch einen blockierten Lauf geleert werden."
        )
        if results:
            os.makedirs("data/raw", exist_ok=True)
            with open(PARTIAL_OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            metrics["partial_output_path"] = PARTIAL_OUTPUT_PATH
            print(f"Partial Run gespeichert -> {PARTIAL_OUTPUT_PATH}")
    else:
        os.makedirs("data/raw", exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        metrics["saved_posts"] = len(results)
        print(f"{len(results)} Posts gescrapt -> {OUTPUT_PATH}")

    if mostly_blocked:
        print(
            "Hinweis: Reddit blockiert aktuell die meisten Public-JSON-Requests mit 403. "
            "Frisches Scraping ist unzuverlaessig; vorhandene scraped_reddit.json kann "
            "weiter fuer Preprocessing genutzt werden."
        )

    saved_metrics = save_reddit_metrics("reddit_scraper_run", metrics)
    print(f"Metrics gespeichert -> data/metrics.json ({saved_metrics['blocked_403_count']}x 403)")


if __name__ == "__main__":
    run()
