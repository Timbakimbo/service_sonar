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

Implemented but API-key dependent:

- Analysis Agent (`agents.analysis_agent`) requires `GEMINI_API_KEY`
- Gap Analysis Agent v2 (`agents.gap_analysis_agent`) requires `GROQ_API_KEY`
- Innovation Agent (`agents.innovation_agent`) requires `GROQ_API_KEY`
- Evaluator Agent (`agents.evaluator_agent`) requires `GROQ_API_KEY`

Not implemented yet:

- Keyword Agent and feedback loop

Deliberately out of scope:

- Central orchestrator. By design, inter-agent communication is file-based via each stage's
  JSON output, and loop control is handled by the Evaluator's action lists plus a human in the
  loop. Stages are run manually in sequence (see Local Run Sequence).

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
python -m agents.innovation_agent
python -m agents.evaluator_agent
```

## Known Limitations

- Reddit public JSON scraping produced a usable dataset (361 posts in the current corpus). Individual re-runs may hit 403 rate-limiting depending on IP/timing; the scraper guards against this by preserving the existing `data/raw/scraped_reddit.json` instead of overwriting it with an empty/blocked run, and writing a separate partial file.
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
