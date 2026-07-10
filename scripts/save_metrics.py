import json
import os
from collections import Counter
from datetime import datetime
from statistics import median
from urllib.parse import urljoin, urlparse

SCRAPED_WEB_PATH = "data/raw/scraped_web.json"
SCRAPED_REDDIT_PATH = "data/raw/scraped_reddit.json"
SCRAPED_FRAGDENSTAAT_PATH = "data/raw/scraped_fragdenstaat.json"
SOURCES_PATH = "data/raw/sources.json"
METRICS_PATH = "data/metrics.json"

# Grobe Domain-Kategorisierung
FORUM_DOMAINS = [
    "gutefrage.net", "rund-ums-baby.de", "urbia.de",
    "eltern.de", "reddit.com", "lehrerforen.de", "baby-vornamen.de",
]
AMT_DOMAINS = [
    "zbfs.bayern.de", "bayernportal.de", "arbeitsagentur.de",
    "stmas.bayern.de", "gesetze-bayern.de", "bamf.de",
    "bmbfsfj.bund.de", "destatis.de", "bavaria.de", "bayern.de",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: str, fallback):
    if not os.path.exists(path):
        return fallback
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_metrics(metrics: dict) -> None:
    os.makedirs(os.path.dirname(METRICS_PATH), exist_ok=True)
    all_metrics = load_json(METRICS_PATH, [])
    all_metrics.append(metrics)
    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, ensure_ascii=False, indent=2)


def word_stats(documents: list[dict]) -> dict:
    counts = sorted(len(str(doc.get("text", "")).split()) for doc in documents)
    if not counts:
        return {"min_words": 0, "max_words": 0, "median_words": 0}
    return {
        "min_words": counts[0],
        "max_words": counts[-1],
        "median_words": int(median(counts)),
    }


def duplicate_url_count(documents: list[dict], base_url: str | None = None) -> int:
    urls = []
    for doc in documents:
        url = str(doc.get("url", "")).strip()
        if not url:
            continue
        if base_url:
            url = urljoin(base_url, url)
        if not url.endswith("/"):
            url = f"{url}/"
        urls.append(url)
    counts = Counter(urls)
    return sum(count - 1 for count in counts.values() if count > 1)


def categorize_domain(domain: str) -> str:
    """Kategorisiert eine Domain als Forum, Amt oder Sonstige."""
    for d in FORUM_DOMAINS:
        if d in domain:
            return "forum"
    for d in AMT_DOMAINS:
        if d in domain:
            return "amt"
    return "sonstige"


def compute_web_metrics(run_label: str) -> dict:
    sources = load_json(SOURCES_PATH, [])
    scraped = load_json(SCRAPED_WEB_PATH, [])

    domains = Counter()
    categories = {"forum": 0, "amt": 0, "sonstige": 0}
    for doc in scraped:
        domain = urlparse(doc.get("url", "")).netloc
        domains[domain] += 1
        categories[categorize_domain(domain)] += 1

    urls_found = len(sources)
    urls_scraped = len(scraped)
    metrics = {
        "source": "web",
        "run_label": run_label,
        "run_timestamp": now_iso(),
        "output_path": SCRAPED_WEB_PATH,
        "urls_found": urls_found,
        "urls_scraped": urls_scraped,
        "filter_rate_pct": round((1 - urls_scraped / urls_found) * 100, 1) if urls_found else 0,
        "file_size_mb": round(os.path.getsize(SCRAPED_WEB_PATH) / (1024 * 1024), 2)
        if os.path.exists(SCRAPED_WEB_PATH) else 0,
        "top_domains": dict(domains.most_common(10)),
        "categories": categories,
    }
    metrics.update(word_stats(scraped))
    return metrics


def compute_reddit_metrics(run_label: str, run_stats: dict | None = None) -> dict:
    run_stats = run_stats or {}
    posts = load_json(SCRAPED_REDDIT_PATH, [])
    subreddit_distribution = Counter(post.get("subreddit", "unknown") for post in posts)

    metrics = {
        "source": "reddit",
        "run_label": run_label,
        "run_timestamp": now_iso(),
        "output_path": SCRAPED_REDDIT_PATH,
        "attempted_subreddits": run_stats.get("attempted_subreddits", 0),
        "attempted_queries": run_stats.get("attempted_queries", 0),
        "attempted_requests": run_stats.get("attempted_requests", 0),
        "successful_requests": run_stats.get("successful_requests", 0),
        "failed_requests": run_stats.get("failed_requests", 0),
        "blocked_403_count": run_stats.get("blocked_403_count", 0),
        "collected_posts": run_stats.get("collected_posts", len(posts)),
        "saved_posts": run_stats.get("saved_posts", len(posts)),
        "filtered_too_short": run_stats.get("filtered_too_short", 0),
        "filtered_too_long": run_stats.get("filtered_too_long", 0),
        "subreddits": dict(subreddit_distribution),
        "interrupted": bool(run_stats.get("interrupted", False)),
        "existing_data_preserved": bool(run_stats.get("existing_data_preserved", False)),
        "blocked_run": bool(run_stats.get("blocked_run", False)),
        "fresh_data_collected": bool(run_stats.get("fresh_data_collected", False)),
        "early_abort_reason": run_stats.get("early_abort_reason", ""),
        "partial_posts_collected": run_stats.get("partial_posts_collected", 0),
        "partial_output_path": run_stats.get("partial_output_path", ""),
        "preserve_reason": run_stats.get("preserve_reason", ""),
    }
    metrics.update(word_stats(posts))
    return metrics


def compute_fragdenstaat_metrics(run_label: str, run_stats: dict | None = None) -> dict:
    run_stats = run_stats or {}
    requests_data = load_json(SCRAPED_FRAGDENSTAAT_PATH, [])
    authority_distribution = Counter(doc.get("behoerde", "unknown") for doc in requests_data)

    metrics = {
        "source": "fragdenstaat",
        "run_label": run_label,
        "run_timestamp": now_iso(),
        "output_path": SCRAPED_FRAGDENSTAAT_PATH,
        "authorities_checked": run_stats.get("authorities_checked", 0),
        "existing_count_before_run": run_stats.get("existing_count_before_run", 0),
        "new_count": run_stats.get("new_count", 0),
        "total_count_after_run": run_stats.get("total_count_after_run", len(requests_data)),
        "duplicate_count": run_stats.get(
            "duplicate_count",
            duplicate_url_count(requests_data, "https://fragdenstaat.de"),
        ),
        "authorities": dict(authority_distribution),
        "api_limitation_note": (
            "FragDenStaat messages API requires OAuth; scraper currently uses "
            "request description/request body and summary fields."
        ),
    }
    metrics.update(word_stats(requests_data))
    return metrics


def save_web_metrics(run_label: str) -> dict:
    metrics = compute_web_metrics(run_label)
    append_metrics(metrics)
    return metrics


def save_reddit_metrics(run_label: str, run_stats: dict | None = None) -> dict:
    metrics = compute_reddit_metrics(run_label, run_stats)
    append_metrics(metrics)
    return metrics


def save_fragdenstaat_metrics(run_label: str, run_stats: dict | None = None) -> dict:
    metrics = compute_fragdenstaat_metrics(run_label, run_stats)
    append_metrics(metrics)
    return metrics


def save_metrics(run_label: str):
    """Backward-compatible entry point for historical web-scraper metrics."""
    print(f"Berechne Web-Kennzahlen fuer Run: {run_label}")
    metrics = save_web_metrics(run_label)
    print(f"Kennzahlen gespeichert -> {METRICS_PATH}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys

    source = "web"
    label = "unnamed_run"
    if len(sys.argv) == 2:
        label = sys.argv[1]
    elif len(sys.argv) >= 3:
        source = sys.argv[1].lower()
        label = sys.argv[2]

    if source == "web":
        metrics = save_web_metrics(label)
    elif source == "reddit":
        metrics = save_reddit_metrics(label)
    elif source == "fragdenstaat":
        metrics = save_fragdenstaat_metrics(label)
    else:
        raise SystemExit("Usage: python scripts/save_metrics.py [web|reddit|fragdenstaat] RUN_LABEL")

    print(f"Kennzahlen gespeichert -> {METRICS_PATH}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
