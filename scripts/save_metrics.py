# scripts/save_metrics.py
import json
import os
from datetime import datetime
from urllib.parse import urlparse

SCRAPED_PATH = "data/raw/scraped_web.json"
SOURCES_PATH = "data/raw/sources.json"
METRICS_PATH = "data/metrics.json"

# Grobe Domain-Kategorisierung
FORUM_DOMAINS = [
    "gutefrage.net", "rund-ums-baby.de", "urbia.de",
    "eltern.de", "reddit.com", "lehrerforen.de", "baby-vornamen.de"
]
AMT_DOMAINS = [
    "zbfs.bayern.de", "bayernportal.de", "arbeitsagentur.de",
    "stmas.bayern.de", "gesetze-bayern.de", "bamf.de",
    "bmbfsfj.bund.de", "destatis.de", "bavaria.de", "bayern.de"
]


def categorize_domain(domain: str) -> str:
    """Kategorisiert eine Domain als Forum, Amt oder News/Sonstige"""
    for d in FORUM_DOMAINS:
        if d in domain:
            return "forum"
    for d in AMT_DOMAINS:
        if d in domain:
            return "amt"
    return "sonstige"


def compute_metrics(run_label: str) -> dict:
    # Sources laden
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        sources = json.load(f)

    # Scraped laden
    with open(SCRAPED_PATH, "r", encoding="utf-8") as f:
        scraped = json.load(f)

    # Wörter
    word_counts = sorted([len(d["text"].split()) for d in scraped])
    median_words = word_counts[len(word_counts) // 2]

    # Dateigröße
    file_size_mb = round(os.path.getsize(SCRAPED_PATH) / (1024 * 1024), 2)

    # Domain Analyse
    domains = {}
    categories = {"forum": 0, "amt": 0, "sonstige": 0}
    for d in scraped:
        domain = urlparse(d["url"]).netloc
        domains[domain] = domains.get(domain, 0) + 1
        categories[categorize_domain(domain)] += 1

    top_domains = dict(sorted(domains.items(), key=lambda x: -x[1])[:10])

    # Filterrate
    urls_found = len(sources)
    urls_scraped = len(scraped)

    metrics = {
        "run_label": run_label,
        "timestamp": datetime.now().isoformat(),
        "urls_found": urls_found,
        "urls_scraped": urls_scraped,
        "filter_rate_pct": round((1 - urls_scraped / urls_found) * 100, 1) if urls_found else 0,
        "file_size_mb": file_size_mb,
        "median_words": median_words,
        "min_words": word_counts[0],
        "max_words": word_counts[-1],
        "top_domains": top_domains,
        "categories": categories
    }

    return metrics


def save_metrics(run_label: str):
    print(f"Berechne Kennzahlen für Run: {run_label}")
    metrics = compute_metrics(run_label)

    os.makedirs("data", exist_ok=True)

    # Bestehende Metrics laden oder neu anlegen
    if os.path.exists(METRICS_PATH):
        with open(METRICS_PATH, "r", encoding="utf-8") as f:
            all_metrics = json.load(f)
    else:
        all_metrics = []

    all_metrics.append(metrics)

    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, ensure_ascii=False, indent=2)

    print(f"Kennzahlen gespeichert → {METRICS_PATH}")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    label = sys.argv[1] if len(sys.argv) > 1 else "unnamed_run"
    save_metrics(label)