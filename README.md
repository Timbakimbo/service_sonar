# Service Sonar

Prototype for an agentic AI workflow around family-related social benefits in the ZBFS/Bavaria context.

The project collects public web, Reddit and FragDenStaat data, preprocesses text, runs topic/sentiment analysis, compares needs with existing services, and prepares later service innovation work.

The pipeline is deliberately manual and has no orchestrator. For the authoritative German
operating procedure—including inputs, outputs, success checks, and the human handoff after
evaluation—see [`RUNBOOK.md`](RUNBOOK.md).

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

Implemented human feedback slice:

- Evaluator recommendations can be accepted, rejected, or deferred via
  `scripts/review_evaluator.py`.
- Accepted keyword additions/removals are consumed by the next manually started Source
  Discovery and Reddit run.

Not implemented yet:

- Automatic application of accepted topic, gap, innovation-rework, and merge decisions by
  the respective domain agents. These decisions are recorded but remain a manual follow-up.

Deliberately out of scope:

- Central orchestrator. By design, inter-agent communication is file-based via each stage's
  JSON output, and loop control is handled by the Evaluator's action lists plus a human in the
  loop. Stages are run manually in sequence (see Local Run Sequence).

Gap Analysis v2 is an intermediate assistive analysis result. It is not a final fachliche Entscheidung.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` if you want to run API-key-dependent agents:

```bash
GEMINI_API_KEY=
GROQ_API_KEY=
```

Do not commit `.env`.

## Local Run Sequence

Check the existing artifacts and the next manual step first:

```bash
python scripts/pipeline_status.py
```

The checker only reads and validates JSON files. It never runs agents, applies Evaluator
actions, or stores pipeline state.

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

The three scrapers may run independently, but preprocessing requires all three regular
scraper outputs. After the Evaluator, stop and review `review_count`, `review_reasons`,
`aggregierte_aktionen`, `rework_warteschlange`, and `keyword_feedback`. Open actions are a
human decision gate, not an automatically executed feedback loop. See the
[`RUNBOOK.md`](RUNBOOK.md#human-in-the-loop-nach-dem-evaluator) for the action matrix.

Review recommendations interactively with `python scripts/review_evaluator.py`. Accepted
keyword decisions are consumed by the next manually started Source Discovery and Reddit run;
no stage is started automatically.

## Known Limitations

- Reddit public JSON scraping produced a usable dataset (361 posts in the current corpus). Individual re-runs may hit 403 rate-limiting depending on IP/timing; the scraper guards against this by preserving the existing `data/raw/scraped_reddit.json` instead of overwriting it with an empty/blocked run, and writing a separate partial file.
- FragDenStaat messages require OAuth; the scraper uses public request description/body and summary fields.
- Web scraping can produce normal robots.txt skips, 403 and 404 responses.
- Analysis, Gap Analysis, Innovation, and Evaluator require external LLM APIs.
- The executable feedback path currently covers keywords; other accepted Evaluator actions
  are recorded but not yet consumed by Gap Analysis or Innovation.
- Existing generated JSON data is kept in the repo as prototype/demo data. New local scratch outputs should not be committed unless intentionally curated.

## Metrics

Scraper metrics are appended to `data/metrics.json`.

```bash
python scripts/save_metrics.py web run_label
python scripts/save_metrics.py reddit run_label
python scripts/save_metrics.py fragdenstaat run_label
```

The web, Reddit and FragDenStaat scrapers also save comparable run metrics automatically after successful/manual runs.
