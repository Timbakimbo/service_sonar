import json
import sys
import os
from ddgs import DDGS
from config.keywords import KEYWORDS

OUTPUT_PATH = "data/raw/sources.json"

def search_ddg(query: str, num_results: int = 10) -> list:
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


def discover_sources() -> list:
    all_sources = []
    seen_urls = set()

    for keyword in KEYWORDS:
        print(f"Suche nach: {keyword}")
        results = search_ddg(keyword)

        for result in results:
            if result["url"] not in seen_urls:
                seen_urls.add(result["url"])
                all_sources.append(result)

    return all_sources


def run():
    print("Source Discovery gestartet ...")
    sources = discover_sources()

    os.makedirs("data/raw", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)

    print(f"{len(sources)} Sources gefunden → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()