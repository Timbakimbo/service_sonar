# Findings & Empirische Erkenntnisse

## Run 1 — Unfiltered (Baseline)

### Daten
- 201 URLs gefunden (Source Discovery)
- 148 erfolgreich gescrapt
- Dateigröße: 57MB
- Median: 1.006 Wörter pro Seite
- Min: 4 Wörter | Max: 317.183 Wörter

### Domain-Verteilung (Top 10)
| Domain | Anzahl | Kategorie |
|--------|--------|-----------|
| zbfs.bayern.de | 13 | Amt |
| bayernportal.de | 11 | Amt |
| sueddeutsche.de | 6 | News |
| tiktok.com | 5 | Social Media |
| elterngeld.de | 4 | Info |
| arbeitsagentur.de | 4 | Amt |
| stmas.bayern.de | 4 | Amt |
| gesetze-bayern.de | 3 | Amt |
| ra-klose.com | 2 | Sonstige |
| misshandeltenachkriegskinder.com | 2 | Sonstige |

### Kategorien
- Forum: 3 | Amt: 49 | Sonstige: 96

### Outlier-Analyse (Top 10 nach Wörtern)
| Wörter | URL | Problem |
|--------|-----|---------|
| 317.183 | destatis.de — Datenreport PDF | PDF, massiver Noise |
| 314.119 | gold.uclg.org — Stuttgart PDF | PDF, irrelevant |
| 280.259 | bmbfsfj.bund.de — Elterngeld Englisch PDF | PDF, falsche Sprache |
| 167.333 | archive.org — Digitalisiertes Buch | Archiv, irrelevant |
| 126.455 | bamf.de — Unbegleitete Minderjährige PDF | PDF, falsches Thema |
| 111.761 | zbfs.bayern.de — Antragsunterlagen PDF | PDF, Formular-Text |
| 65.378 | shop.bioeg.de | PDF, irrelevant |
| 64.000 | huggingface.co — vocab.txt | ML Vocab-Datei, komplett irrelevant |
| 55.734 | zbfs.bayern.de — SGB IX Antrag PDF | PDF, Formular-Text |
| 37.449 | udel.edu — Deutsche Wortliste | Wortliste, irrelevant |

### Probleme identifiziert
- PDFs werden ungefiltert gescrapt — massiver Noise und Dateigröße
- Zu viele Amt-Seiten — DDG rankt offizielle Seiten höher als Foren
- TikTok, HuggingFace — DDG liefert völlig irrelevante Domains
- Kaum echte Foren im Output (nur 3 von 148)
- Durchschnitt als Kennzahl unbrauchbar — ein PDF treibt ihn auf 12.389 Wörter

### Designentscheidungen aus Run 1
- **Zwei-Ebenen Content Filter** — URL-Level + Content-Level
- **Median statt Durchschnitt** — robuster gegen Outlier
- **Social Media Blacklist** — TikTok, Instagram, HuggingFace auf URL-Level geblockt

---

## Run 2 — Filtered

### Daten
- 178 URLs gefunden (nach URL-Filter)
- 136 erfolgreich gescrapt
- Dateigröße: **2.3MB** (vs. 57MB — Reduktion 96%)
- Median: 906 Wörter | Min: 1 Wort | Max: 50.168 Wörter

### Probleme identifiziert
- Min 1 Wort hat Filter überlebt — Content Filter noch nicht wasserdicht
- Max 50.168 knapp unter Limit

### Designentscheidungen aus Run 2
- **Amt-Seiten bleiben drin** — wichtige Referenz für Gap Analysis Agent
- **Dedizierte Quellen für Nutzererfahrungen** — Reddit + FragdenStaat als separate Module
- **Keywords bleiben minimal** — Keyword Agent übernimmt Erweiterung nach BERTopic

---

## Reddit Scraper — Erster Durchlauf

### Daten
- 361 Posts gescrapt → scraped_reddit.json
- Subreddits: r/germany, r/LegalAdviceGerman, r/Eltern, r/de
- r/Bayern komplett geblockt (403) — privates Subreddit

### Erkenntnisse
- Öffentliche JSON Endpoints funktionieren ohne API Key
- Reddit Self-Service API seit November 2025 eingestellt
- Reddit ist reichhaltigste Foren-Quelle im System
- Score + num_comments als potenzielle Relevanz-Signale gespeichert

---

## FragdenStaat Scraper — Entwicklung

### Problem: Messages API leer
- Erste Version nutzte `/api/v1/message/` — lieferte 0 Objekte ohne Auth
- robots.txt blockt `/anfrage/` — BeautifulSoup als Alternative nicht erlaubt
- Lösung: `description` direkt aus dem Request Objekt — enthält Anfragetext

### Daten (nach Fix)
- 68 Anfragen gespeichert → scraped_fragdenstaat.json
- ZBFS (ID 12904): 16 Anfragen
- Familienkasse Bayern Nord (ID 14032): 1 Anfrage
- StMAS Bayern Familie (ID 11209): 45 Anfragen
- Inkrementelles Scraping aktiv — Duplikate werden via URL-Cache vermieden
- Antworttext bleibt leer — Behördenantworten nur über OAuth zugänglich

### Erkenntnisse
- ZBFS hat auf FragdenStaat keine Elterngeld-Anfragen — hauptsächlich Schwerbehinderung und Impfschäden
- ~50% der Anfragen betreffen Impfschäden/Corona — nicht primär familienbezogen
- StMAS breiter: Kita, Schwerbehinderung, Asyl, Corona, Pflege
- Familienkasse Bayern Nord: nur 1 Anfrage — sehr geringe FragdenStaat-Nutzung
- Wichtige Familienthemen fehlen noch im Datensatz: Pflegegeld, Fördermittel, Kita-Zuschuss
- Hypothese: Keyword Agent wird diese Themen nach BERTopic Durchlauf selbst identifizieren

### Schlussfolgerungen
- FragdenStaat zeigt wo Bürger Transparenz einfordern, nicht wo sie Hilfe suchen
- Reddit bleibt primäre Quelle für Erfahrungsberichte
- Thematische Filterung durch Evaluator Agent nötig — nicht alle Anfragen sind familienbezogen

---

## Preprocessing — Entwicklung & Designentscheidungen

### Zwei-Output Strategie
BERTopic und GerVader brauchen unterschiedliche Textformen:
- **cleaned_text** — PII anonymisiert, Satzstruktur erhalten → für GerVader
- **preprocessed_text** — lemmatisiert, Stopwords raus, URLs raus → für BERTopic

### Probleme & Fixes
| Problem | Ursache | Fix |
|---------|---------|-----|
| Ultra langsam (erste Version) | `nlp()` zweimal pro Dokument aufgerufen | `nlp.pipe()` mit batch_size=32, ein Call pro Doc |
| `[MISC]` in cleaned_text (494 von 565) | Fallback `f"[{ent.label_}]"` für alle spaCy Labels | Nur PER/LOC/ORG ersetzen, Rest original lassen |
| URLs als BERTopic Topics | URL-Tokens nicht gefiltert | `token.like_url` + explizite URL-Pattern Filter |
| `source: unknown` für Web Scraper Docs | Feld nicht gesetzt | `"source": "web"` im Web Scraper ergänzt |

### Optimierung
- `nlp.pipe()` statt einzeln → von "ultra lange" auf ~3 Minuten für 565 Dokumente
- Ein einziger `nlp()` Call pro Dokument für beide Outputs

### Aktueller Stand
- 565 Dokumente preprocesst
- 0 leere preprocessed_texts
- 0 MISC-Artefakte
- 0 URL-Tokens in preprocessed_text
- Median preprocessed_text: 135 Tokens
- Quellen: Web (136) + Reddit (361) + FragdenStaat (68)

---

## Sentiment-Analyse — Versionskonflikt & Fix

### Problem
- `germansentiment` Library nutzt veraltete `batch_encode_plus` API
- Konflikt mit transformers 5.x das BERTopic via sentence-transformers braucht
- germansentiment + sentence-transformers nicht gleichzeitig installierbar

### Fix
- germansentiment durch direkten transformers pipeline Aufruf ersetzt
- Modell: `oliverguhr/german-sentiment-bert` (gleiches Modell, direkter Aufruf)
- Versionsunabhängig, kein Konflikt

---

## Analysis Agent — BERTopic Tuning

### Problem: Mega-Cluster
- Erste Version: nur 4 Topics, Topic 0 enthielt 527 von 565 Dokumenten (93%)
- Downstream Gap Analysis wäre damit unmöglich

### Diagnose
- Embedding Model unterdimensioniert (MiniLM 384 dim) — verschwommen bei semantisch ähnlichen Themen
- HDBSCAN `cluster_selection_method='eom'` greedy merging — kollabiert sub-themes
- Topic-Labels durch nicht-gefilterte Stopwords noisy

### Fix (via Claude Code Plan Mode)
| Lever | Vorher | Nachher | Effekt |
|-------|--------|---------|--------|
| Embedding | MiniLM default | `paraphrase-multilingual-mpnet-base-v2` (768 dim) | Trennt Elterngeld/Familiengeld/Kindergeld |
| HDBSCAN | `eom`, min_cluster_size=5 | `leaf`, min_cluster_size=8, min_samples=2 | Bricht Mega-Cluster auf |
| UMAP | n_neighbors=10 | n_neighbors=15, random_state=42 | Stabilere Manifold |
| Vectorizer | ngrams=(1,3), no stopwords | ngrams=(1,2), spaCy German stopwords, min_df=3 | Lesbare Labels |
| Representation | Default | KeyBERT + MMR(diversity=0.3) | Interpretierbare Topic-Namen |
| Outliers | Verworfen | `reduce_outliers(strategy="embeddings")` | Vollständige Coverage |

### Ergebnis nach Tuning
- **25 Topics** statt 4
- Größtes Topic: 50 Dokumente (8.8%) statt 527 (93%)
- Echte Sub-Themen erkennbar:
  - Familiengeld Bayern
  - Schwerbehinderung/Versorgungsamt
  - Elterngeldstelle/Bescheid
  - Kindergeld
  - Schulpflicht/Einschulung
  - Bearbeitungszeit/Behörde
  - Schwangerschaft/Kinderarzt
  - Landeserziehungsgeld
  - Pflege

### Verbleibende Probleme
- 25 Topics über Zielbereich (8-15)
- Redundante Elterngeld-Topics (5, 9, 11, 23 ähnlich)
- Sprach-Noise Topics (Topic 4, 6, 12, 13 — englische/sprachbezogene Cluster)
- Behörden-Boilerplate Topics (Topic 8, 18 — Cookies/Footer-Text)

### Designentscheidung: Topic Consolidation
- Diese Probleme werden NICHT durch weiteres Parameter-Tuning gelöst
- Sondern durch den Evaluator Agent — er identifiziert redundante und irrelevante Topics
- Demonstriert genau den Mehrwert eines LLM-basierten Reasoning Layers

---

## Architektur-Erkenntnisse

### Agent vs. Hardcoded Pipeline — Designentscheidung
**Definition echter Agent:** LLM als Reasoning-Layer, autonome Entscheidungen, nicht deterministisch.
**Definition hardcoded Modul:** Deterministischer Workflow mit festen Regeln.

### Hardcoded Module
| Modul | Begründung |
|-------|------------|
| Source Discovery | Arbeitet Keywords deterministisch ab |
| Web Scraper | Klare Regeln, deterministisch |
| Reddit Scraper | Public JSON Endpoints, deterministisch |
| FragdenStaat Scraper | Öffentliche API, deterministisch, inkrementell |
| Preprocessing | spaCy Pipeline, deterministisch |

### Echter Agent (Claude API / kostenlose Modelle)
| Agent | Modell | Begründung |
|-------|--------|------------|
| Analysis Agent | Gemini 2.5 Flash | Interpretiert BERTopic/Sentiment im Kontext sozialer Dienstleistungen |
| Gap Analysis Agent | Groq `llama-3.3-70b-versatile` | Reasoning ob Problem wirklich eine Lücke, ein Prozessproblem oder eine Informationslücke ist |
| Innovation Agent | Offen (Claude Haiku / DeepSeek / Groq möglich) | Kreative Ideengenerierung |
| Evaluator Agent | Offen | Komplexes Judgment über alle Outputs |
| Keyword Agent | Kostenlos geplant | Entscheidet welche Keywords rausfliegen |

### Kommunikation zwischen Agents
- Sequentiell: Analysis → Gap Analysis → Innovation → Evaluator
- Evaluator aggregiert Feedback aller Agents:
  1. Rejected + Feedback → zurück an Innovation Agent
  2. Keyword Feedback → zurück an Keywords (Feedback Loop)

### Konzept "Agent passt Parameter selbst an"
- Aktuell setzen wir BERTopic Parameter manuell
- Konzept für nächste Iteration: Analysis Agent bewertet Clustering-Qualität und tunt Parameter selbst
- Für Prototyp pragmatisch entschieden — manuell jetzt, autonom später

### Evaluator Agent — Aufgaben konkretisiert
1. **Ideen bewerten** — sind die generierten Service-Ideen sinnvoll und umsetzbar?
2. **Topics validieren** — gehören die Topics wirklich zum Thema Familie? Impfschäden → raus, Pflegegeld → rein
3. **Keyword Feedback** — welche Keywords brachten irrelevante Topics? Welche neuen würden relevantere Daten bringen?
4. **Konvergenz prüfen** — wann ist das Themenspektrum vollständig?
5. **Redundanz-Erkennung** — ähnliche Topics zusammenführen (z.B. Elterngeld 5, 9, 11, 23)
6. **Noise-Filtering** — Sprach-Cluster und Boilerplate-Topics als irrelevant markieren

Diese Aufgaben sind die direkte Spezifikation aus unseren manuellen Iterationen.

---


## Reference Builder — bestehende Leistungen

### Ziel
Der Gap Analysis Agent benötigt eine strukturierte Referenz bestehender Leistungen, um Bürgerprobleme gegen vorhandene Angebote abgleichen zu können.

### Entwicklung
Ursprünglich war geplant, bestehende Referenzeinträge über ein Migrationsskript in ein neues Schema zu überführen.

Während der Entwicklung wurde entschieden:

- kein separates Migrationsskript
- alte `existing_services.json` löschen
- Build-Reference Pipeline anpassen
- Referenzdatenbank vollständig neu erzeugen

### Ergebnis
- `existing_services.json` neu aufgebaut
- 77 bestehende Leistungen extrahiert
- Deutsches v2-Schema verwendet
- Enthaltene Leistungstypen:
  - Geldleistung
  - Beratung
  - Förderprogramm
  - Sachleistung
  - Rechtsanspruch
  - Verfahrensleistung
- Beratungen und Rechtsansprüche werden ausdrücklich als Leistungen behandelt
- Private Angebote werden zwar gespeichert, zählen im Gap Agent aber nicht als vollwertige staatliche Bedarfsabdeckung

### Erkenntnis
Die Referenzdatenbank ist für die Qualität der Gap Analysis zentral. Wenn die Referenz zu breit oder zu unsauber ist, kann der Gap Agent echte Lücken übersehen oder unpassende Leistungen matchen.

---

## Gap Analysis Agent — Implementierung

### Ziel
Der Gap Analysis Agent klassifiziert relevante Topics aus dem Analysis Agent anhand bestehender Leistungen.

Input:

- `data/analysis/analysis_output.json`
- `data/reference/existing_services.json`

Output:

- `data/gap_analysis/gap_analysis_output.json`

### Klassifikationen
Der Agent unterscheidet:

| Klasse | Bedeutung |
|--------|-----------|
| `echte_luecke` | Keine bestehende Leistung deckt den Bedarf substanziell ab |
| `prozessproblem` | Leistung existiert, aber Zugang, Bearbeitung oder Zuständigkeit sind problematisch |
| `informationsluecke` | Leistung existiert, wird aber nicht verstanden oder gefunden |
| `bereits_abgedeckt` | Leistung deckt Bedarf sauber ab |
| `irrelevant` | Topic passt nicht zum familienbezogenen Leistungskontext |

### Backend
- Groq API
- Modell: `llama-3.3-70b-versatile`
- Ein einziger LLM-Call für alle relevanten Topics
- JSON Output via `response_format={"type": "json_object"}`

### Technische Fixes
| Problem | Fix |
|---------|-----|
| Topic-IDs uneinheitlich (`int` vs. `str`) | Topic-IDs konsequent als String normalisiert |
| JSON Response teilweise mit Markdown-Fences | Robustes JSON Parsing ergänzt |
| Output konnte abgeschnitten werden | `max_tokens` gesetzt |
| LLM erfand Matching Services | Post-Validation gegen Referenzdatenbank |
| Behörden wurden als Leistungen gematcht | Ungültige Matches werden entfernt |
| Unsichere Fälle nicht sichtbar | `needs_review` Flag ergänzt |
| Bewertung schwer prüfbar | `confidence` Feld ergänzt |

---

## Gap Analysis Agent — Erste Ergebnisse

### Datenbasis
- 15 relevante Topics aus dem Analysis Agent
- 77 bestehende Leistungen aus der Referenzdatenbank
- 1 Groq-Call für alle Topics

### Ergebnis nach Validierung
| Kategorie | Anzahl |
|-----------|--------|
| Prozessproblem | 11 |
| Informationslücke | 4 |
| Echte Lücke | 0 |
| Bereits abgedeckt | 0 |
| Irrelevant | 0 |

Zusätzliche Kennzahlen:

- Review-Fälle: 1
- Entfernte ungültige Matching Services: 1

### Beispiele plausibler Klassifikationen
| Topic | Kernproblem | Klassifikation | Matching |
|-------|-------------|----------------|----------|
| 2 | Probleme beim Bayerischen Familiengeld | Prozessproblem | Bayerisches Familiengeld |
| 12 | Zuständigkeit und Auszahlung beim Elterngeld | Prozessproblem | Elterngeld |
| 16 | Familien suchen umfassende Unterstützung | Informationslücke | Familienpatenschaften, Familienunterstützung |
| 27 | Mütter suchen emotionale Unterstützung | Informationslücke | Familienberatungsdienste, psychosoziale Beratung |

### Problematische Klassifikationen
| Topic | Problem | Fragwürdiges Matching |
|-------|---------|----------------------|
| 0 | Aufenthaltsrecht / Migrationshintergrund | Bayerisches Familiengeld, Elterngeld |
| 10 | gesundheitliche Herausforderungen / Gesundheitsamt | Kinderkrankengeld, Mutterschaftsgeld |

### Erkenntnisse
- Technisch läuft der Gap Analysis Agent stabil.
- Die JSON-Ausgabe ist valide und vollständig.
- Die Post-Validation entfernt erfundene Matching Services.
- Der Agent erkennt viele Themen als Prozessprobleme, weil die meisten Bürgerprobleme bestehende Leistungen betreffen.
- 0 echte Lücken wirken fachlich fragwürdig und müssen weiter untersucht werden.
- Die Matching-Qualität hängt stark von der Qualität und Granularität der Referenzdatenbank ab.
- Reines LLM-Matching ist nicht ausreichend zuverlässig.
- Ein semantischer Retrieval-Schritt vor dem LLM könnte die Service-Zuordnung verbessern.

### Schlussfolgerung
Der Gap Analysis Agent ist als erste Version implementiert und pipeline-fähig. Er ist jedoch noch keine finale Entscheidungsinstanz. Für den nächsten Entwicklungsschritt braucht es entweder einen semantischen Service-Retriever oder einen Evaluator Agent, der die Gap-Klassifikationen prüft.

---

## Methodische Erkenntnisse

### Datenquellen im Vergleich
| Quelle | Output | Qualität | Zweck |
|--------|--------|----------|-------|
| Web Scraper | 136 Seiten | Gemischt | Amt-Referenz für Gap Analysis |
| Reddit Scraper | 361 Posts | Hoch | Echte Nutzererfahrungen |
| FragdenStaat | 68 Anfragen | Sehr hoch | IFG-Anfragen direkt an Behörde |
| Existing Services Reference | 77 Leistungen | Mittel | Abgleich bestehender Leistungen |
| Gap Analysis Output | 15 Topics | Erste Version | Prozess-/Informationslücken ableiten |

### Content Filter
- Zwei-Ebenen-Ansatz bewährt sich
- Median robuster als Durchschnitt
- 50.000 Wörter als Max bewusst großzügig
- Reddit Min: 20 Wörter | FragdenStaat Min: 3 Wörter
- Bug: 1 Wort hat Filter überlebt — Fix ausstehend

### Thematische Erkenntnisse
- ZBFS-Themenspektrum breiter als erwartet
- BERTopic findet nach Tuning konkrete Pain Points: Bearbeitungszeit, Bescheid-Probleme, Elterngeldstelle
- Wichtige Familienleistungen erscheinen organisch im Output: Familiengeld, Landeserziehungsgeld, Kindergeld, Schulpflicht
- Nicht-familiäre Themen (Impfschäden, Schwerbehinderung) sind im Output und müssen vom Evaluator gefiltert werden

---

## Aktueller Präsentationsstand

### Fertig
- Source Discovery
- Web Scraper
- Reddit Scraper
- FragdenStaat Scraper
- Preprocessing
- Sentiment Analyse
- BERTopic Tuning
- Analysis Agent
- Reference Builder
- Gap Analysis Agent v1

### Teilweise fertig
- Qualität der Gap Analysis
- Service-Matching gegen bestehende Leistungen
- Review-Logik für unsichere Matches

### Offen
- Innovation Agent
- Evaluator Agent
- Keyword Agent
- Feedback Loop
- Orchestrator
- Semantisches Retrieval für bessere Service-Zuordnung

### Zentrale Erkenntnis für die Präsentation
Der schwierigste Teil des Systems ist nicht mehr die reine Topic-Erkennung, sondern das korrekte Mapping von Bürgerproblemen auf bestehende Leistungen. Genau hier zeigt sich der Bedarf für eine Kombination aus strukturierter Referenzdatenbank, LLM-Reasoning, Validierungslogik und späterem Evaluator Agent.