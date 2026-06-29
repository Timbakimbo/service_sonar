# Service Sonar

Prototype for an agentic AI workflow around family-related social benefits in the ZBFS/Bavaria context.

The project collects public web, Reddit and FragDenStaat data, preprocesses text, runs topic/sentiment analysis, compares needs with existing services, and prepares later service innovation work.

## Current Status

Implemented and locally runnable without private API keys:

- Source Discovery (`agents.source_discovery_agent`)
- Web Scraper (`agents.scraping_agents.webscraping_agent`)
- Reddit Scraper (`agents.scraping_agents.reddit_scraper`)
- FragDenStaat Scraper (`agents.scraping_agents.fragdenstaat_scraper`)
- Preprocessing (`agents.preprocessing`)
- Orchestrator status runner (`agents.orchestrator`)

Implemented but API-key dependent:

- Analysis Agent (`agents.analysis_agent`) requires `GEMINI_API_KEY`
- Gap Analysis Agent v2 (`agents.gap_analysis_agent`) requires `GROQ_API_KEY`

Not implemented yet:

- Innovation Agent / Service Innovation Agent
- Evaluator Agent
- Keyword Agent and feedback loop
- Full end-to-end orchestration

Gap Analysis v2 is an intermediate assistive analysis result. It is not a final fachliche Entscheidung.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` if you want to run API-key-dependent agents:

```bash
GEMINI_API_KEY=
GROQ_API_KEY=
```

Do not commit `.env`.

## Local Run Sequence

```bash
python -m agents.source_discovery_agent
python -m agents.scraping_agents.webscraping_agent
python -m agents.scraping_agents.reddit_scraper
python -m agents.scraping_agents.fragdenstaat_scraper
python -m agents.preprocessing
python -m agents.analysis_agent
python -m agents.gap_analysis_agent
```

For a transparent status overview:

```bash
python -m agents.orchestrator
```

The orchestrator currently checks expected artifacts, API-key availability and planned components. It does not run the full pipeline automatically.

## Known Limitations

- Reddit public JSON scraping is currently unreliable and often returns 403 responses. Existing `data/raw/scraped_reddit.json` can still be used for downstream preprocessing.
- FragDenStaat messages require OAuth; the scraper uses public request description/body and summary fields.
- Web scraping can produce normal robots.txt skips, 403 and 404 responses.
- Analysis and Gap Analysis require external LLM APIs.
- Existing generated JSON data is kept in the repo as prototype/demo data. New local scratch outputs should not be committed unless intentionally curated.

## Metrics

Scraper metrics are appended to `data/metrics.json`.

```bash
python scripts/save_metrics.py web run_label
python scripts/save_metrics.py reddit run_label
python scripts/save_metrics.py fragdenstaat run_label
```

The web, Reddit and FragDenStaat scrapers also save comparable run metrics automatically after successful/manual runs.
