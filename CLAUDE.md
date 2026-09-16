# Service Sonar — Project Context for Claude Code

## What is Service Sonar?
A multi-agent system (MAS) that scrapes public forums and government data sources
to identify unmet citizen needs in family-related social services in Bavaria (ZBFS —
Zentrum Bayern Familie und Soziales). The system finds gaps in existing services and
generates innovation proposals.

This is a university semester project — bachelor thesis at FAU Erlangen-Nürnberg.
Focus is on demonstrating Agentic AI in practice, not commercial production code.

## Architecture (hybrid MAS)
The system explicitly mixes hardcoded modules and LLM-based agents:

**Hardcoded modules (deterministic, no LLM):**
- Source Discovery (DDG search via keywords)
- Web Scraper (BeautifulSoup + robots.txt compliance)
- Reddit Scraper (public JSON endpoints)
- FragdenStaat Scraper (public IFG API)
- Preprocessing (spaCy: tokenization, lemmatization, PII anonymization)

**LLM Agents:**
- Analysis Agent — interprets BERTopic + sentiment output in domain context
- Gap Analysis Agent v2 — two-pass gap classification and cluster recommendations via Groq
- Innovation Agent — generates one grounded service idea per relevant gap cluster via Groq
- Evaluator Agent — four-pass validation, ranking, convergence and keyword feedback via Groq

## Pipeline Flow
1. Keywords → Source Discovery → URLs
2. Web Scraper + Reddit Scraper + FragdenStaat Scraper (parallel) → raw JSON
3. Preprocessing → cleaned_text (for sentiment) + preprocessed_text (for BERTopic)
4. Analysis Agent → topics + sentiment + LLM interpretation
5. Gap Analysis Agent → identified gaps
6. Innovation Agent → service ideas
7. Evaluator Agent → ranked output + structured action lists
8. Human terminal review → accepted/rejected/deferred decisions as JSON
9. Accepted keyword decisions → next manually started discovery/scraping run

## Data Flow
- `data/raw/` — scraped data per source
- `data/preprocessed/preprocessed.json` — unified preprocessed corpus
- `data/analysis/analysis_output.json` — Analysis Agent output (input for Gap Analysis)
- `data/gap_analysis/gap_analysis_output_v2.json` — clustered Gap Analysis output
- `data/innovation/innovation_output.json` — generated service ideas
- `data/evaluation/evaluator_output.json` — evaluations and proposed actions
- `data/evaluation/human_decisions.json` — optional human decisions created during review
- `data/metrics.json` — run metrics for evaluation

## Design Decisions
- **Plain Python, no framework** — every step transparent for thesis defense
- **Single Responsibility per module** — each agent/module in its own file
- **Two-output preprocessing** — BERTopic needs lemmatized tokens, GerVader needs sentence structure
- **Human-controlled feedback** — current, provenance-matched accepted decisions may affect a
  later manual run; rejected decisions are closed/non-consumable; deferred decisions remain open
  and keep the Human Gate active but are non-consumable; legacy and stale decisions never apply
- **No orchestrator** — stages remain manual and communicate through JSON artifacts
- **Two-level content filter** — URL-level (early) + content-level (after scraping)
- **Configured backends** — Gemini Flash for Analysis, Groq for Innovation, and selectable
  Groq/OpenAI backends for Gap Analysis and Evaluator

## Current State
- Full forward pipeline implemented through Innovation and four-pass Evaluation
- Current curated corpus: 555 preprocessed documents (126 web + 361 Reddit + 68 FragDenStaat)
- Current committed output: 25 Topics (16 relevant), 16 Gaps in 11 clusters and 10 Innovations
- Final Evaluator output is complete: all 16 Gaps were evaluated in Pass 2, 0 Gaps were skipped,
  and the Human Gate is closed
- Read-only pipeline status/validation and German operational runbook implemented
- Terminal Human-in-the-Loop review implemented; accepted keyword feedback is executable
- Topic removal, Gap reclassification and accepted Innovation rework are consumed only by the
  next manually started target agent; merge decisions remain visible human guidance and never
  merge Innovations automatically
- Every new Evaluator output carries `evaluator_run_id`; action IDs use stable Topic/Gap/cluster
  identity. The final committed Human Decisions belong to the current Evaluator run, whose
  output is complete with `failed_pass_count=0`; no fresh pipeline run is currently required.
- Evaluator/Innovation preserve prior outputs on missing configuration or complete LLM failure;
  partial outputs expose failed passes/clusters.
- Human Gate means only unresolved current `human_required` actions. Every new
  `echte_luecke` assertion creates a mandatory `real_gap_review` action.
- A legacy Evaluator artifact without complete run/action provenance requires a fresh Evaluator
  run and is refused by Human Review before prompts or writes.

## Key Files
- `agents/analysis_agent.py` — current Analysis Agent (BERTopic + sentiment + Gemini)
- `agents/preprocessing.py` — spaCy pipeline
- `agents/scraping_agents/` — three scrapers
- `agents/evaluator_agent.py` — four-pass evaluation and deterministic action aggregation
- `scripts/review_evaluator.py` — terminal Human-in-the-Loop review
- `scripts/pipeline_status.py` — read-only artifact validation and next-stage status
- `config/keywords.py` — seed keywords plus accepted runtime decisions
- `RUNBOOK.md` — authoritative manual operating procedure
- `BRAINSTORM.md` — open questions and design decisions log
- `FINDINGS.md` — empirical findings from each run

## Important Constraints
- Don't add new frameworks (LangChain, CrewAI etc.) — plain Python is a deliberate choice
- Don't hardcode keyword lists or topic labels — system should discover these
- Respect the agent vs module distinction — don't add LLM calls to deterministic modules
- All German-language content — use multilingual or German-specific models
- Never turn status/review helpers into an automatic pipeline runner or regeneration loop
