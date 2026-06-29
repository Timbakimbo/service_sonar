import json
import os
from collections import Counter
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

EXPECTED_ARTIFACTS = [
    ("Source Discovery", Path("data/raw/sources.json"), "python -m agents.source_discovery_agent"),
    ("Web Scraper", Path("data/raw/scraped_web.json"), "python -m agents.scraping_agents.webscraping_agent"),
    ("Reddit Scraper", Path("data/raw/scraped_reddit.json"), "python -m agents.scraping_agents.reddit_scraper"),
    ("FragDenStaat Scraper", Path("data/raw/scraped_fragdenstaat.json"), "python -m agents.scraping_agents.fragdenstaat_scraper"),
    ("Preprocessing", Path("data/preprocessed/preprocessed.json"), "python -m agents.preprocessing"),
    ("Analysis Agent", Path("data/analysis/analysis_output.json"), "python -m agents.analysis_agent"),
    ("Reference Services", Path("data/reference/existing_services.json"), "python scripts/build_reference.py"),
    ("Gap Analysis Agent v2", Path("data/gap_analysis/gap_analysis_output_v2.json"), "python -m agents.gap_analysis_agent"),
]

PLANNED_COMPONENTS = [
    ("Innovation Agent", Path("agents/innovation_agent.py")),
    ("Evaluator Agent", Path("agents/evaluator_agent.py")),
]


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def count_records(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        data = load_json(path)
    except Exception as exc:
        return f"unreadable ({exc})"
    if isinstance(data, list):
        return f"{len(data)} records"
    if isinstance(data, dict):
        if "documents" in data and isinstance(data["documents"], list):
            return f"{len(data['documents'])} documents"
        if "gaps" in data and isinstance(data["gaps"], list):
            return f"{len(data['gaps'])} gaps"
        if "services" in data and isinstance(data["services"], list):
            return f"{len(data['services'])} services"
        return f"object keys: {', '.join(list(data.keys())[:5])}"
    return type(data).__name__


def duplicate_url_count(path: Path) -> int:
    if not path.exists():
        return 0
    data = load_json(path)
    urls = Counter(doc.get("url", "") for doc in data if isinstance(doc, dict))
    return sum(count - 1 for count in urls.values() if count > 1)


def env_status(name: str) -> str:
    return "set" if os.getenv(name) else "missing"


def run() -> int:
    print("Service Sonar Pipeline Status")
    print("=============================")
    print("This orchestrator is a status runner, not a full end-to-end executor yet.\n")

    print("Artifacts:")
    for label, path, command in EXPECTED_ARTIFACTS:
        status = "OK" if path.exists() else "MISSING"
        print(f"- {label}: {status} ({count_records(path)})")
        print(f"  command: {command}")

    frag_path = Path("data/raw/scraped_fragdenstaat.json")
    duplicates = duplicate_url_count(frag_path)
    if duplicates:
        print(f"\nWarning: FragDenStaat output currently contains {duplicates} duplicate URL rows.")
        print("The scraper now deduplicates by request id and normalized URL on future runs.")

    print("\nEnvironment:")
    print(f"- GEMINI_API_KEY: {env_status('GEMINI_API_KEY')} (Analysis Agent)")
    print(f"- GROQ_API_KEY: {env_status('GROQ_API_KEY')} (Gap Analysis Agent)")

    print("\nPlanned components:")
    for label, path in PLANNED_COMPONENTS:
        state = "implemented" if path.exists() else "not implemented"
        print(f"- {label}: {state}")

    print("\nSuggested local sequence:")
    for _label, _path, command in EXPECTED_ARTIFACTS:
        print(f"- {command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
