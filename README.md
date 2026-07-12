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
- Gap Analysis Agent v2 (`agents.gap_analysis_agent`) requires `GROQ_API_KEY` by default,
  or `OPENAI_API_KEY` with `GAP_BACKEND=openai`
- Innovation Agent (`agents.innovation_agent`) requires `GROQ_API_KEY`
- Evaluator Agent (`agents.evaluator_agent`) requires `GROQ_API_KEY` by default, or
  `OPENAI_API_KEY` with `EVALUATOR_BACKEND=openai`

Implemented feedback loop:

- Evaluator recommendations are normalized as `auto_apply`, `human_required`, or
  `suggestion_only` actions.
- Every Evaluator run has a unique `evaluator_run_id`; actions use deterministic IDs based on
  semantic action type plus stable Topic/Gap/cluster identity. Human decisions from another run
  or for a changed action are reported as stale and ignored.
- Human-required recommendations can be accepted, rejected, or deferred via
  `scripts/review_evaluator.py`.
- Accepted keyword additions/removals are consumed by the next manually started Source
  Discovery and Reddit run.
- Low-risk auto actions and accepted human decisions are consumed by the next manually
  started Gap Analysis and Innovation runs where applicable.
- Accepted current human actions are resolved and may be consumed; rejected actions are resolved
  and never consumed. Deferred actions are postponed, remain unresolved/open in Human Review and
  continue to activate the Human Gate, but are never consumed downstream.

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

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` if you want to run API-key-dependent agents:

```bash
GEMINI_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=
EVALUATOR_BACKEND=groq
OPENAI_EVALUATOR_MODEL=gpt-4.1-mini
GROQ_EVALUATOR_MODEL=llama-3.3-70b-versatile
GAP_BACKEND=groq
OPENAI_GAP_MODEL=gpt-4.1-mini
GROQ_GAP_MODEL=llama-3.3-70b-versatile
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

Review recommendations interactively with `python scripts/review_evaluator.py`. By default,
the review UI shows only `human_required` actions; use `--include-auto` or
`--include-suggestions` for inspection. No stage is started automatically.

Every initial `echte_luecke` assertion creates a separate `real_gap_review` action, even when
the Evaluator LLM otherwise accepts the Gap. Accepting, rejecting, or deferring that action
records Human Review but never reclassifies the Gap or starts another stage automatically.

Evaluator and Innovation preserve an existing valid output when configuration/client setup
fails or when every eligible LLM call fails. Partial outputs explicitly list failed passes or
clusters. A legitimate Innovation run with zero eligible clusters is recorded as an empty-input
success.

## Known Limitations

- Reddit public JSON scraping produced a usable dataset (361 posts in the current corpus). Individual re-runs may hit 403 rate-limiting depending on IP/timing; the scraper now aborts early on fully blocked diagnostic runs, preserves the existing `data/raw/scraped_reddit.json`, and records blocked/stale metrics for `pipeline_status.py`.
- Reddit also preserves the retained corpus when requests technically succeed but produce zero
  usable posts; partial posts are written only to the separate partial artifact.
- FragDenStaat messages require OAuth; the scraper uses public request description/body and summary fields.
- Web scraping can produce normal robots.txt skips, 403 and 404 responses.
- Analysis, Gap Analysis, Innovation, and Evaluator require external LLM APIs.
- Evaluator feedback is intentionally bounded: low-risk topic/gap corrections may be auto-applied; keywords and innovation changes still require human approval; code/scraper changes remain suggestions only.
- Existing generated JSON data is kept in the repo as prototype/demo data. New local scratch outputs should not be committed unless intentionally curated.
- The committed legacy `human_decisions.json` predates action provenance and is intentionally
  ignored by current code. `pipeline_status.py` reports the accompanying Evaluator artifact as
  `LEGACY EVALUATOR OUTPUT — FRESH EVALUATOR RUN REQUIRED`; Human Review refuses it before any
  prompt or write. A fresh controlled Evaluator run and Human Review are required.

## Offline Tests

Normal test collection is offline-safe; the DDG smoke test is opt-in.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Set `SERVICE_SONAR_RUN_DDG_SMOKE=1` only when a deliberate network smoke test is authorized.

## Metrics

Scraper metrics are appended to `data/metrics.json`.

```bash
python scripts/save_metrics.py web run_label
python scripts/save_metrics.py reddit run_label
python scripts/save_metrics.py fragdenstaat run_label
```

The web, Reddit and FragDenStaat scrapers also save comparable run metrics automatically after successful/manual runs.
