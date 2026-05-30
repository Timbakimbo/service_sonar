# Service Sonar – Brainstorm & Offene Fragen

## Offene Fragen

### BERTopic Output
- [ ] 25 Topics ist über Zielbereich (8-15) — Evaluator muss konsolidieren
- [ ] Redundante Elterngeld-Topics (5, 9, 11, 23) zusammenführen
- [ ] Sprach-Noise Topics (4, 6, 12, 13) als irrelevant markieren
- [ ] Behörden-Boilerplate Topics (8, 18) als irrelevant markieren

### Quellen-Strategie
- [ ] Keywords mit Forum-Signalwörtern erweitern — wird später vom Keyword Agent übernommen
- [ ] Min 1 Wort in Web Scraper durchgekommen — Content Filter noch nicht wasserdicht

### Redundanz & Relevanzsignal
- [ ] Semantische Redundanz: Embedding-Ähnlichkeit zwischen Topics — ab welchem Threshold zusammenführen?
- [ ] Relevanzsignal Kombination:
  - Häufigkeit (BERTopic Topic-Gewicht)
  - Negativem Sentiment
  - Reddit Score + num_comments
- [ ] Genaue Gewichtung erst nach erstem vollständigem Durchlauf entscheidbar

### Feedback Loop
- [ ] Keyword Agent: wie misst er ob ein Keyword "schwach" ist?
- [ ] Bereits gescrapter Content bleibt — kein Re-Scraping für alte Keywords
- [ ] Keyword Agent erst nach erstem vollständigem BERTopic Durchlauf sinnvoll

### Datenbank
- [ ] Phase 1: JSON reicht für Prototyp
- [ ] Phase 2: SQLite wenn Datenmenge es erfordert — wann genau switchen?

### Agents vs. Hardcoded
- [ ] Genaue Tool-Definition für echte Agents noch offen
- [ ] Wie testen wir ob der Keyword Agent sinnvolle Entscheidungen trifft?
- [ ] Konzept "Analysis Agent passt BERTopic Parameter selbst an" — für nächste Iteration

## Getroffene Entscheidungen

### Architektur — Agent vs. Hardcoded Pipeline
Bewusste Entscheidung: Agents nur wo Reasoning nötig ist, hardcoded wo Regeln ausreichen.

**Hardcoded Module:**
- Source Discovery — arbeitet Keywords deterministisch ab
- Web Scraper — klare Regeln, deterministisch
- Reddit Scraper — Public JSON Endpoints, deterministisch
- FragdenStaat Scraper — öffentliche API, deterministisch, inkrementell
- Preprocessing — deterministisch, spaCy

**Echter Agent (Claude API / kostenlose Modelle):**
- Analysis Agent → Gemini 2.5 Flash
- Gap Analysis Agent → Gemini 2.5 Flash
- Innovation Agent → Claude Haiku / DeepSeek V4
- Evaluator Agent → Claude Haiku
- Keyword Agent → kostenlos

### Modell-Strategie
- Einfache Reasoning-Aufgaben → kostenlose Modelle (Gemini 2.5 Flash)
- Komplexere Aufgaben → günstige paid Modelle (Claude Haiku, DeepSeek V4)
- Kein Sonnet nötig — bewusste Kostenstrategie

### BERTopic Tuning (Analysis Agent)
- Embedding: `paraphrase-multilingual-mpnet-base-v2` (768 dim) statt MiniLM default
- HDBSCAN: `cluster_selection_method='leaf'`, min_cluster_size=8, min_samples=2
- UMAP: n_neighbors=15, random_state=42
- Vectorizer: ngrams=(1,2), spaCy German stopwords, min_df=3
- Representation: KeyBERT + MMR(diversity=0.3)
- Outlier reduction: `reduce_outliers(strategy="embeddings")` für vollständige Coverage

### Sentiment-Analyse
- `germansentiment` Library raus wegen Versionskonflikt
- Direkter transformers pipeline Aufruf mit `oliverguhr/german-sentiment-bert`
- Gleiches Modell, versionsunabhängig

### FragdenStaat — Quellen & Strategie
- **3 Behörden** werden abgefragt:
  - ZBFS (ID 12904) — Elterngeld, Schwerbehinderung, Familiengeld
  - Familienkasse Bayern Nord (ID 14032) — Kindergeld (Nürnberg)
  - StMAS Bayern Familie (ID 11209) — Bayerisches Staatsministerium für Familie
- **Inkrementelles Scraping** — bestehende Anfragen bleiben erhalten, nur neue werden hinzugefügt
- API: `description` direkt aus Request Objekt — Messages API braucht OAuth

### Reddit API
- Self-Service API seit November 2025 eingestellt — PRAW nicht mehr möglich
- Öffentliche JSON Endpoints als pragmatische Alternative
- r/Bayern privat und geblockt — aus Liste entfernt
- Aktive Subreddits: r/germany, r/LegalAdviceGerman, r/Eltern, r/de

### Orchestrierung
- Plain Python, kein Framework
- Jeder Agent/Modul = eigene Python-Datei, Single Responsibility
- Orchestrator bleibt als Modul — koordiniert Reihenfolge und Feedback Loop

### Suchmaschine
- DuckDuckGo (DDG) als primäre Quelle
- Google Custom Search API nicht verfügbar (403 Bug seit 2026)

### Content Filter Strategie
Filter auf zwei Ebenen:

1. **Source Discovery (URL-Level)**
   - .pdf URLs ausschließen
   - Social Media Blacklist: tiktok.com, instagram.com, facebook.com, huggingface.co, twitter.com, youtube.com

2. **Content-Level (nach Scraping)**
   - Web Scraper: unter 100 Wörter und über 50.000 Wörter → verwerfen
   - Reddit: unter 20 Wörter → verwerfen
   - FragdenStaat: unter 3 Wörter → verwerfen

### Preprocessing Strategie
- Zwei-Output: cleaned_text (für Sentiment) + preprocessed_text (für BERTopic)
- PII Anonymisierung via spaCy NER: PER/LOC/ORG (nicht MISC)
- URLs aus preprocessed_text gefiltert
- spaCy `de_core_news_lg` für beste NER-Qualität
- `nlp.pipe()` für Batch-Performance

### Evaluator Agent — Aufgaben (aus manuellen Iterationen abgeleitet)
1. Ideen bewerten — sind Service-Ideen umsetzbar?
2. Topics validieren — gehören sie zum Familienkontext?
3. Keyword Feedback — welche Keywords schwach?
4. Konvergenz prüfen — ist Themenspektrum vollständig?
5. Redundanz-Erkennung — ähnliche Topics zusammenführen
6. Noise-Filtering — Sprach-Cluster und Boilerplate raus

### Metrics & Runs
- Nur Kennzahlen werden historisiert, keine Rohdaten
- `data/metrics.json` akkumuliert alle Runs
- Median statt Durchschnitt — robuster gegen Outlier

### Keywords
- Minimale Starter-Keywords — kein manuelles Erweitern
- Keyword Agent übernimmt Erweiterung nach erstem BERTopic Durchlauf

## Nächste Schritte
- [x] Content Filter Source Discovery ✅
- [x] Content Filter Web Scraper ✅
- [x] Run 1 + Run 2 Metrics ✅
- [x] Reddit Scraper ✅
- [x] FragdenStaat Scraper (ZBFS + Familienkasse + StMAS) ✅
- [x] Preprocessing Modul ✅
- [x] Analysis Agent inkl. BERTopic Tuning ✅
- [x] Präsentation ✅
- [ ] Min-Wörter Bug in Web Scraper fixen (1 Wort durch Filter)
- [ ] Gap Analysis Agent (Gemini 2.5 Flash)
- [ ] Service Innovation Agent (Claude Haiku / DeepSeek)
- [ ] Evaluator Agent (Claude Haiku)
- [ ] Keyword Agent + Feedback Loop
- [ ] Orchestrator
- [x] FINDINGS.md + BRAINSTORM.md ins Repo legen (für Claude Code Kontext)
- [ ] Umbenennung: nicht-Agent Module aus `agents/` Ordner raus, neuer `modules/` Ordner