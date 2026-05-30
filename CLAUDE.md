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

**LLM Agents (Gemini 2.5 Flash + transformers tools):**
- Analysis Agent — interprets BERTopic + sentiment output in domain context
- Gap Analysis Agent — identifies real gaps vs existing ZBFS services
- Innovation Agent — generates service ideas for identified gaps
- Evaluator Agent — central feedback hub, validates ideas, updates keywords

## Pipeline Flow
1. Keywords → Source Discovery → URLs
2. Web Scraper + Reddit Scraper + FragdenStaat Scraper (parallel) → raw JSON
3. Preprocessing → cleaned_text (for sentiment) + preprocessed_text (for BERTopic)
4. Analysis Agent → topics + sentiment + LLM interpretation
5. Gap Analysis Agent → identified gaps
6. Innovation Agent → service ideas
7. Evaluator Agent → ranked output + keyword feedback loop

## Data Flow
- `data/raw/` — scraped data per source
- `data/preprocessed/preprocessed.json` — unified preprocessed corpus
- `data/analysis/analysis_output.json` — Analysis Agent output (input for Gap Analysis)
- `data/metrics.json` — run metrics for evaluation

## Design Decisions
- **Plain Python, no framework** — every step transparent for thesis defense
- **Single Responsibility per module** — each agent/module in its own file
- **Two-output preprocessing** — BERTopic needs lemmatized tokens, GerVader needs sentence structure
- **No hardcoded keyword expansion** — Keyword Agent will handle this after first full run
- **Two-level content filter** — URL-level (early) + content-level (after scraping)
- **Cost optimization** — Gemini Flash for simple reasoning, Claude Haiku for complex judgment

## Current State
- All scrapers working (565 documents: 136 web + 361 reddit + 68 fragdenstaat)
- Preprocessing working (spaCy lemmatization + NER-based PII anonymization)
- Analysis Agent partially working — BERTopic produces a mega-cluster (93% of docs in one topic), Sentiment + LLM interpretation works

## Key Files
- `agents/analysis_agent.py` — current Analysis Agent (BERTopic + sentiment + Gemini)
- `agents/preprocessing.py` — spaCy pipeline
- `agents/scraping_agents/` — three scrapers
- `config/keywords.py` — minimal seed keywords (will be expanded by Keyword Agent later)
- `BRAINSTORM.md` — open questions and design decisions log
- `FINDINGS.md` — empirical findings from each run

## Important Constraints
- Don't add new frameworks (LangChain, CrewAI etc.) — plain Python is a deliberate choice
- Don't hardcode keyword lists or topic labels — system should discover these
- Respect the agent vs module distinction — don't add LLM calls to deterministic modules
- All German-language content — use multilingual or German-specific models