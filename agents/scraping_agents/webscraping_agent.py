import json
import os
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse

INPUT_PATH = "data/raw/sources.json"
OUTPUT_PATH = "data/raw/scraped_web.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ServiceSonar/1.0)"
}

DEFAULT_CRAWL_DELAY = 2  # Sekunden zwischen Requests


def get_robots_parser(base_url: str) -> RobotFileParser:
    rp = RobotFileParser()
    rp.set_url(f"{base_url}/robots.txt")
    try:
        rp.read()
    except Exception:
        pass
    return rp


def get_crawl_delay(rp: RobotFileParser) -> float:
    delay = rp.crawl_delay("*")
    return delay if delay else DEFAULT_CRAWL_DELAY


def scrape_url(url: str) -> dict | None:
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else ""

        date = None
        for tag in soup.find_all("time"):
            date = tag.get("datetime") or tag.text.strip()
            break

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)

        return {
            "url": url,
            "title": title,
            "text": text,
            "date": date,
            "scraped_at": datetime.now().isoformat(),
            "source": "web"
        }

    except Exception as e:
        print(f"Fehler bei {url}: {e}")
        return None


def run():
    print("Web Scraper gestartet...")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        sources = json.load(f)

    results = []
    robots_cache = {}  # robots.txt pro Domain cachen

    for i, source in enumerate(sources):
        url = source["url"]
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # robots.txt cachen pro Domain
        if base_url not in robots_cache:
            robots_cache[base_url] = get_robots_parser(base_url)
        rp = robots_cache[base_url]

        # Prüfen ob scrapen erlaubt
        if not rp.can_fetch("*", url):
            print(f"[{i+1}/{len(sources)}] Übersprungen (robots.txt): {url}")
            continue

        print(f"[{i+1}/{len(sources)}] Scrape: {url}")
        result = scrape_url(url)
        if result:
            results.append(result)

        # Crawl-Delay respektieren
        time.sleep(get_crawl_delay(rp))

    os.makedirs("data/raw", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"{len(results)} Seiten gescrapt → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()