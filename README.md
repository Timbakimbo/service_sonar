## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Verwendung
```bash
# Source Discovery starten
python -m agents.source_discovery_agent

# Gesamte Pipeline starten (folgt)
python -m agents.orchestrator
```

## Tech Stack
- Python 3.10
- DDGs (Websuche)
- PRAW (Reddit)
- BeautifulSoup (HTML Parsing)
- spaCy (NLP Preprocessing)
- BERTopic (Topic Modeling)
- GerVader (Deutsche Sentiment-Analyse)
- Anthropic Claude API (Synthese)