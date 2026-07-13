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
- Gap Analysis Agent v2 (2-Pass + deterministisches Clustering)
- Innovation Agent
- Evaluator Agent (4-Pass-Kaskade)

### Teilweise fertig
- Qualität der Gap Analysis
- Service-Matching gegen bestehende Leistungen
- Review-Logik für unsichere Matches
- Pipeline-Metriken (Web/Reddit/FragdenStaat) — Evaluator liest per-Source; „complete" nach einmaligem Scraper-Re-Run

### Offen
- Quantitative Bewertung des neuen Keyword-Feedback-Laufs
- Verarbeitung akzeptierter Topic-/Gap-/Innovation-Aktionen durch die Fach-Agents
- Semantisches Retrieval für bessere Service-Zuordnung

### Bewusst verworfen
- Zentraler Orchestrator — Inter-Agent-Kommunikation file-basiert über JSON-Outputs,
  Loop-Control via Evaluator-Action-Listen + Human-in-the-Loop

### Zentrale Erkenntnis für die Präsentation
Der schwierigste Teil des Systems ist nicht mehr die reine Topic-Erkennung, sondern das korrekte Mapping von Bürgerproblemen auf bestehende Leistungen. Dafür kombiniert das System inzwischen strukturierte Referenzdaten, LLM-Reasoning, deterministische Validierung und eine vierstufige Evaluation mit menschlicher Freigabe.

---

## Gap Analysis Agent v2 — 2-Pass + deterministisches Clustering

### Motivation (Schwächen v1)
- `empfehlung_innovation` war Boilerplate (11/15 Gaps fast wortgleich "einfacher transparenter Antragsprozess")
- Redundante Elterngeld-Topics (7/9/12/14/20/22) wurden als getrennte Gaps ohne Querverweis behandelt
- `kernproblem` zu generisch — nannte nicht die Customer-Journey-Phase

### Architektur-Umstellung 1-Call → 2-Pass
| Pass | Aufgabe | Backend |
|------|---------|---------|
| Pass 1 | Klassifikation, customer_journey_phase, cluster_id, matching_services — 1 Call für alle Topics | Llama 3.3 70B |
| Pass 2 | EINE konkrete Empfehlung pro relevantem Cluster — 1 Call pro Cluster | Llama 3.3 70B |

Begründung: Der 1-Call-Ansatz überlastete das LLM (Klassifikation + Cluster + Phase + Empfehlung gleichzeitig). Pass 2 zwingt strukturell zu Konkretheit, weil eine Cluster-Empfehlung mehrere Topic-Facetten gleichzeitig adressieren muss.

### Schlüssel-Erkenntnis: LLM-Clustering ist run-instabil
Zwei Prompt-Iterationen scheiterten — Llama 3.3 kodierte die *Facette* in die `cluster_id` (`elterngeld_fuer_vaeter`, `elterngeld_hoehe`) statt auf Leistungsebene zu clustern, selbst nach explizitem Negativbeispiel im Prompt. **Fix: deterministische Konsolidierung** über den dominanten `matching_service` statt LLM-Clustering. Restriktive Bündelungs-Regel (gleicher Primär-Service UND gleiche Klassifizierung UND kein blockierender Review-Grund), sonst `solo_<topic_id>`. So bleibt z.B. T0 (Migration, fälschlich auf Familiengeld gematcht) sauber isoliert. Die LLM-cluster_id bleibt als `cluster_id_llm` zur Diagnose erhalten.

**Methodisches Learning:** Wo das LLM eine *Konsistenz-* statt *Reasoning-Leistung* erbringen muss (stabile Labels über Runs), ist Determinismus im Code überlegen — analog zur Matching-Validierung in v1.

### Ergebnis v2
- Elterngeld-Topics korrekt zu `elterngeld_prozessproblem` (4) + `elterngeld_informationsluecke` (2) gebündelt
- Empfehlungen konkret (BayernID/ELSTER/Stakeholder/Phase), Boilerplate via Generic-Detection geflaggt
- Pass-2-Calls von 14 auf 11 reduziert durch Clustering
- schema_version 1.2-de, neuer Output `gap_analysis_output_v2.json` (alte Datei unangetastet)

---

## Innovation Agent v1 — Cluster → konkrete Idee

### Aufbau
- Input: `gap_analysis_output_v2.json` (cluster-basiert) + Referenz
- 1 Groq-Call pro relevantem Cluster → genau EINE Innovation, die alle Topics adressiert
- Skip-Logik: bereits_abgedeckt/irrelevant-Cluster + Solos mit Scope-Review-Grund (z.B. solo_0 Migration)

### Determinismus-Split (Grounding gegen Halluzination)
- **Code-gesetzt:** addressierte_topics, betroffene_leistungen, cluster_id, klassifizierung, adressierte_phasen
- **LLM:** Titel, konkrete Lösung, Träger, Integrationspunkte, Hürden, Aufwand, Priorität

### Empirisches Learning: Titel-Schranke
Erste Validierung nutzte Wort-Untergrenze (min 5 Wörter) → flaggte **10/10** Innovationen, weil deutsche Komposita-Titel ("Digitaler Elterngeld-Assistent") natürlicherweise 2–4 Wörter haben. **Fix: Zeichen-Schranke (20–80) statt Wortzählung.** Senkte Fehlalarme von 10/10 auf 5/10 (verbleibende sind echte Kurz-Titel wie "ElternGuide"). Train-of-thought: `split()` zählt Bindestrich-Komposita als 1 Wort — Wortgrenzen sind für deutsche Verwaltungssprache untauglich.

### Träger-Whitelist
Alias-Map (Vollname ↔ Abkürzung, "Zentrum Bayern Familie und Soziales" ↔ "ZBFS") + kuratierte öffentliche Träger. L-Bank (BW-Förderbank) bewusst ausgeschlossen — kein bayerischer Träger; LfA/BayernLabo/KfW fehlen im Datensatz.

---

## Evaluator Agent — 4-Pass-Kaskade (schließt den MAS-Kreislauf)

### Architektur
| Pass | Aufgabe |
|------|---------|
| Pass 1 | Topic-Evaluation (alle 28 Topics; in_scope/noise/redundancy/verdict) |
| Pass 2 | Gap-Evaluation (nur in_scope-Topics; Rest deterministisch skipped) |
| Pass 3 | Innovation-Evaluation (Domain-/Integrationspunkte-/Konvergenz-Plausibilität) |
| Pass 4 | Aggregation: Priorisierung, Konvergenz-Status, Keyword-Feedback |

Determinismus-Split: evaluation_ids, aggregierte_aktionen, Cross-Pass-Override (Gap remove/reclassify ⇒ Innovation rework), priorisierung-Vollständigkeit setzt der Code; Plausibilität/Begründungen/Briefings das LLM.

### Cross-Pass-Konsistenz als Code-Garantie
Pass 2 (Gap) ist die Wahrheit. Sagt das LLM in Pass 3 "accept", obwohl der zugrundeliegende Gap remove/reclassify ist, **überschreibt der Code** auf "rework" (gap_basis_fraglich). Zusätzlich Plausibilitäts-Overrides: `traeger_domain_plausibel=false` oder `integrationspunkte_plausibel=false` bei verdict=accept → Code-Override auf rework. Diese Overrides fangen *innere Inkonsistenz* (Flag=false aber accept).

### Prompt-Schärfung v2 — was funktionierte, was nicht (ehrlich)
Vier Schwächen im ersten Evaluator-Output adressiert (nur Prompts + 2 Code-Overrides, kein Modellwechsel):

| Schwäche | Erwartung | Ergebnis |
|----------|-----------|----------|
| 1: Träger-Domain (INN_006 Kultusministerium für Gesundheit) | tdp=false + rework | ✅ **getroffen** |
| 2: Integrationspunkte (BayernID/ELSTER bei Foren/Beratung) | INN_009 + INN_010 ipp=false | ⚠️ **teilweise** — INN_010 ✅, **INN_009 verfehlt** |
| 3: Konvergenz INN_001+004+008 | gemeinsamer Pattern-Cluster | ✅ **getroffen** (sogar +INN_002) |
| 4: Noise vs out-of-scope (T0/T1/T4) | noise=false, nur out-of-scope | ✅ **getroffen** |

### Methodisches Learning: Prompt-Schärfung vs. Modell-Limit
**Prompt-Schärfung wirkte** bei Konvergenz (Pattern- statt Domänen-Labeling) und der Noise/out-of-scope-Trennung — beides mit Llama 3.3 zuverlässig im Lauf. Das ist NICHT der Gemini-Fall.

**INN_009 ist ein echter Teil-Miss (nicht beschönigt):** ElternGuide für Schwangere/junge Eltern hat nur BayernID; die Lösung sagt "über BayernID auf bestehende Daten zugreifen". Llama wertete das als legitimen personalisierten Datenzugriff, nicht als niedrigschwellige Beratung ohne Auth-Bedarf — laut Spec hätte ipp=false kommen müssen. Im Gegensatz zum Mütter-Forum (anonym, klar) ist das ein **Grenzfall im Urteil**, kein Inkonsistenz-Fall.

**Kernerkenntnis für die Thesis:** Die deterministischen Overrides korrigieren nur *innere Inkonsistenz* (Flag=false aber accept). Sie können einen **falsch-positiven Flag-Wert** (LLM setzt fälschlich ipp=true) NICHT korrigieren — dafür müsste das Modell den Flag richtig setzen. INN_009 ist genau dieser Fall: ein Urteils-Schwäche-Problem bei Grenzfällen, kein Code-Problem. Hier — und nur hier — wäre ein stärkeres Reasoning-Modell (Gemini) der Hebel, nicht mehr Prompt-Text. **Vorgemerkter Gemini-Fall: Pass-3-Integrationspunkte-Plausibilität bei Grenzfällen.**

### Verifiziert
- Override-Pfade (b)/(c) isoliert getestet (Flag=false + accept → korrekt rework mit Briefing) — in diesem Lauf nicht gefeuert, weil das LLM selbst schon konsistent war
- priorisierung deterministisch garantiert vollständig (fehlende accept-IDs werden mit `deterministisch_angehaengt: true` ergänzt)
- Konvergenz-Bündelung über `normalize_konvergenz_label` (Token-Sort) run-stabil

---

## Pipeline-Metriken & Robustheit (Team-Integration, AlexIonkin)

Beiträge aus dem Branch `test-and-metrics-updates`, integriert ohne den Orchestrator-Stub.
Der Orchestrator wurde bewusst komplett verworfen (file-basierte Inter-Agent-Kommunikation +
Evaluator-Action-Listen + Human-in-the-Loop statt zentraler Koordinator).

### save_metrics erweitert (Web + Reddit + FragdenStaat)
- `scripts/save_metrics.py` liefert jetzt vergleichbare Run-Metriken für alle drei Quellen
  (`save_web_metrics`, `save_reddit_metrics`, `save_fragdenstaat_metrics`) statt nur Web.
- Web/Reddit/FragdenStaat-Scraper rufen ihre Metrik-Funktion nach dem Lauf selbst auf.
- **Evaluator-Kopplung (erledigt):** `metrics.json` ist eine Liste von Run-Records, jeder neue
  Record getaggt mit `source` (web/reddit/fragdenstaat); Legacy-Web-Läufe haben kein `source`.
  `build_source_stats` gruppiert die Liste jetzt nach Quelle (Legacy = web) und nimmt pro Quelle
  den jüngsten Record → `source_stats_status="complete"`, sobald alle drei Quellen vorliegen,
  sonst `partial`. **Verbleibend (Daten, kein Code):** Die drei Scraper müssen einmal mit dem
  erweiterten `save_metrics` laufen, damit Reddit/FragdenStaat-Records in `metrics.json` landen
  (aktuell nur Legacy-Web → `partial`).

### Robustheit & Hygiene
- **Graceful API-Key-Handling:** `get_groq_client()` / `get_gemini_client()` brechen nicht mehr
  beim Import hart ab, sondern geben eine Hilfemeldung und None zurück — Pipeline-Stufen ohne
  Key laufen sauber durch statt zu crashen. Client wird durch die Pass-Funktionen gefädelt.
- **FragdenStaat-Dedup-Fix:** relative und absolute URLs werden vor dem Abgleich normalisiert
  (`urljoin`), sodass erneute Läufe bestehende Anfragen nicht mehr duplizieren.
- **Reddit-Re-Run-Schutz:** Der bestehende Datensatz (361 Posts) war/ist verwertbar. Der Scraper
  schützt ihn jetzt vor einem blockierten *erneuten* Lauf: bei ≥80 % 403er oder komplett
  fehlgeschlagenen Requests wird `scraped_reddit.json` NICHT mit Leerdaten überschrieben, sondern
  erhalten; ein Partial-Output landet separat unter `data/raw/scraped_reddit_partial.json`
  (per `.gitignore` ausgeschlossen). Kein Beleg, dass Reddit generell unzuverlässig ist — der
  Schutz greift nur, wenn ein konkreter Lauf tatsächlich blockiert wird.
- `.env.example`, `groq==1.5.0` in `requirements.txt`, `.gitignore`-Policy für Scratch-/Partial-Files.

### Lokaler Testlauf (Windows, frischer Clone)
- Manuelle `python -m ...`-Ausführung aller hardcoded Stufen ohne API-Keys erfolgreich.
- Source Discovery: 220 URLs gefunden, 26 gefiltert, 175 akzeptiert.
- Web Scraper: 175 Quellen → 135 Seiten; robots.txt-Skips / 403 / 404 ohne Crash gehandhabt.
- Preprocessing: 135 Web + 361 Reddit + 136 FragdenStaat = 632 Dokumente.
- FragdenStaat-Dedup-Verdacht (68 + 68 = 136) war der Auslöser für den Normalisierungs-Fix oben.

---

## Manueller End-to-End-Workflow (ohne Orchestrator)

### Implementiert
- `RUNBOOK.md` ist die operative Anleitung mit Pipeline-Graph, Stage-Verträgen,
  Erfolgskriterien, Fehlerfällen und Human-in-the-Loop-Aktionsmatrix.
- Das README verweist als kurzer Einstieg auf das Runbook und den Status-Check.
- `scripts/pipeline_status.py` validiert read-only alle Stage-Artefakte oder eine einzelne Stage.
  Es prüft JSON-Lesbarkeit, Top-Level-Struktur, Pflichtfelder und nichtleere Kerndaten.
- Statusausgabe unterscheidet `READY`, `BLOCKED`, `OUTPUT VALID` und `OUTPUT INVALID` und nennt
  den nächsten manuellen Befehl. Es werden keine Agents gestartet und keine State-Files geschrieben.
- Evaluator-Reviews, aggregierte Aktionen und Keyword-Vorschläge werden als
  `HUMAN DECISION REQUIRED` sichtbar gemacht.
- 14 isolierte Tests decken Artefaktvalidierung, Human Gate, Review-Persistenz,
  Keyword-Anwendung und Reddit-Runtime-Metriken ab.

### Prüfung am vorhandenen Datenstand
- Alle neun Stage-Outputs sind technisch valide.
- Der Evaluator-Output hat `review_count=0`, aber bewusst offene Human-Aktionen:
  - 3 Innovationen regenerieren (`INN_003`, `INN_006`, `INN_010`)
  - 15 Topics entfernen
  - 2 Konvergenzgruppen fachlich zusammenführen
- Keyword-Feedback wird als konkreter Human-Output erzeugt:
  - schwach: `ZBFS`, `Zentrum Bayern Familie & Soziales`,
    `Familienunterstützung Bayern Probleme`
  - vorgeschlagen: `Elterngeldantrag`, `Familiengeldantrag`, `Kinderbetreuung`,
    `Pflegeunterstützung`, `Sorgerechtsberatung`
- Konvergenz ist noch nicht erreicht; als fehlend werden Pflege, Sorgerecht/Umgangsrecht,
  Kita-Zuschuss, Fördermittel und Unterhalt genannt.
- `source_stats_status` ist weiterhin `partial`, bis alle drei Scraper mit der erweiterten
  Metrik-Erfassung erneut gelaufen sind.

### Evaluator-Rechte-Matrix und erweiterter Feedbackloop
Der Evaluator ist jetzt als Supervisor-Agent mit begrenzten Rechten modelliert. Seine Aktionen
werden in drei Stufen getrennt:

| Stufe | Wirkung |
|---|---|
| `auto_apply` | Low-risk-Korrektur wird beim nächsten manuellen Ziel-Agent-Lauf berücksichtigt. |
| `human_required` | Mensch muss akzeptieren, ablehnen oder vertagen. |
| `suggestion_only` | Nur Team-/Engineering-Hinweis, nie automatische Anwendung. |

Damit muss nicht jede Kleinigkeit durch HIL, aber riskante Entscheidungen bleiben kontrolliert:
Keywords und Innovationen benötigen Freigabe; technische Noise-Removals und sichere
Gap-Reklassifikationen dürfen automatisch wirken.

Der Feedback-Pfad ist über `agents/human_feedback.py` erweitert:
Source Discovery und Reddit lesen akzeptierte Keyword-Entscheidungen; Gap Analysis liest
Topic-Remove und Gap-Reclassify; Innovation liest Rework-Briefings und Merge-Gruppen. Eine Stage
wird weiterhin nie automatisch gestartet — der Mensch wählt den Wiederanlaufpunkt.

### Human-Review und erster ausführbarer Feedback-Slice
- `scripts/review_evaluator.py` zeigt Evaluator-Aktionen im Terminal und erfasst pro Aktion
  `accepted`, `rejected` oder `deferred` plus optionale menschliche Notiz.
- Entscheidungen werden file-basiert in `data/evaluation/human_decisions.json` gespeichert;
  bereichsweise spätere Reviews überschreiben frühere Bereiche nicht.
- Der Pipeline-Status zählt akzeptierte und abgelehnte Aktionen nicht mehr als offenen Human Gate;
  vertagte Empfehlungen bleiben offen.
- Source Discovery und Reddit verwenden beim nächsten manuellen Lauf die Seed-Keywords plus
  akzeptierte Ergänzungen minus akzeptierte Entfernungen. Damit ist der Keyword-Feedback-Pfad
  Evaluator → Mensch → JSON → neuer manueller Datenlauf technisch geschlossen.
- Topic-Remove, Gap-Reclassify, Innovation-Rework und Merge werden strukturiert erfasst,
  geroutet und von Gap-/Innovation-Agent beim nächsten manuellen Lauf verarbeitet. Automatisch
  angewendete Korrekturen werden im Output sichtbar markiert.

---

## Vollständiger E2E-Testlauf — 30.06.2026

### Funnel
| Stufe | Ergebnis |
|---|---:|
| Wirksame Keywords | 25 |
| Gefundene / akzeptierte Quellen | 250 / 207 |
| Web / Reddit / FragDenStaat | 146 / 361 / 68 |
| Preprocessing-Dokumente | 575 |
| Topics gesamt / relevant | 26 / 17 |
| Gap-Cluster | 9 |
| Innovationen | 9 |
| Evaluator accept / rework | 5 / 4 |

Alle Stage-Outputs waren technisch valide. Gap Analysis bildete aus 17 relevanten Topics neun
Cluster (8 Prozessprobleme, 9 Informationslücken, keine echte Lücke) und lief ohne Review-Fall.
Innovation erzeugte neun Ideen; `INN_006 Familiengeld-Assistent` wurde bereits dort als
`needs_review` markiert. Der Evaluator beendete alle vier Pässe ohne Fehler und meldete
`source_stats=complete`.

### Evaluator und menschliche Entscheidungen
Der Evaluator erzeugte 4 Rework-, 3 Reclassify-, 9 Topic-Remove- und 2 Merge-Aktionen. Im
Terminal-Review wurden unter anderem `Pflegestellen`, `Kita-Finanzierung` und
`Familienförderung` als neue Keywords sowie die Entfernung von `ZBFS` akzeptiert. Drei
Noise-Topic-Entfernungen und beide Merge-Gruppen wurden ebenfalls akzeptiert; weitere fachliche
Aktionen wurden vertagt.

Damit ist belegt, dass ein Mensch verständlichen, aktionsbezogenen Output erhält und Entscheidungen
persistieren kann. Die ehemals offene Rückkopplung zu Gap-/Innovation-Agent wurde anschließend
geschlossen: Auto-Apply- und akzeptierte Human-Aktionen dienen nun als reproduzierbarer manueller
Input für den nächsten Stage-Lauf.

### Empirische Learnings
- `ZBFS` erzeugte fachfremde wissenschaftliche Treffer zu „zeroing barrier functions“. Die
  Evaluator-Empfehlung zum Entfernen wurde durch den Web-Run empirisch bestätigt.
- Generische Vorschläge wie `Kinderbetreuung` erhöhten die Quellenbreite, brachten aber auch
  schweizerische Angebote und Stellenanzeigen. Keyword-Vorschläge benötigen künftig expliziten
  Bayern- und Problemkontext.
- 207 akzeptierte Discovery-URLs führten weiterhin zu 146 verwertbaren Webseiten. Die neuen
  Keywords veränderten damit vor allem die Zusammensetzung, nicht die Größe des 575er-Korpus.
- Reddit blockierte 55 von 55 Public-JSON-Requests mit 403. Der Schutzpfad erhielt nach manueller
  Unterbrechung den bestehenden Datensatz mit 361 Posts und protokollierte den Lauf korrekt.
  Anschließend wurde der Scraper um Diagnose-Abbruch und blocked/stale-Metriken ergänzt; der
  Status-Checker unterscheidet dadurch technische JSON-Validität von frischer Datenqualität.
- FragDenStaat fand keine neuen Anfragen und übersprang alle 68 bestehenden Einträge ohne Duplikate.
- Keine `echte_luecke` trotz breiterem Themenspektrum bleibt ein Signal, die Kriterien und das
  Service-Matching weiter zu prüfen.

---

## Abschlussaudit und Correctness-Fixes — 12.07.2026

### Datenstand vor den Fixes

- 207 Sources; 146 Web-Dokumente; 361 erhaltene Reddit-Posts; 68 FragDenStaat-Anfragen
- 575 Preprocessing-/Analysis-Dokumente
- 26 Topics: 17 relevant, 9 irrelevant
- 17 Gaps in 14 Clustern: 10 Prozessprobleme, 2 Informationslücken,
  3 bereits abgedeckt, 2 irrelevant, 0 echte Lücken
- 9 Innovationen; Evaluator: 7 accept, 2 rework
- 29 normalisierte Aktionen: 11 auto_apply, 17 human_required, 1 suggestion_only
- needs_review: Gap 2, Innovation 3, Evaluator 0
- human_decisions.json: 54 Entscheidungen (31 accepted, 11 rejected, 12 deferred)

### Bestätigte Probleme

Die vorhandenen Human Decisions waren über mehrere Evaluator-Läufe akkumuliert und nur über
Aktionstyp plus wiederverwendbare Ziele wie `INN_005` verbunden. Dadurch konnten alte Rework-
oder Merge-Entscheidungen auf fachlich andere neue Innovationen wirken. Die bestehende
`human_decisions.json` besitzt keine passende Run-/Action-Provenienz, gilt daher als stale und
kann nicht als finale fachliche Evidenz verwendet werden.

Weitere bestätigte Correctness-Probleme waren: konsumierbare deferred Auto-Aktionen, zu breite
Evaluator-Autonomie ohne explizites Unambiguous-Signal, fehlende Pflichtprüfung neuer
`echte_luecke`-Behauptungen, Überschreiben valider Evaluator-/Innovation-Outputs bei kompletten
LLM-Fehlern, falsche Human-Gate-Aktivierung durch Auto-/Suggestion-/Review-Zähler, doppelte
Innovations-Ränge, möglicher Reddit-Corpusverlust bei null verwendbaren Posts sowie ein
Windows-Encoding-Crash im Text-Status.

### Umgesetzte begrenzte Korrekturen

- `evaluator_run_id` und semantische, stabile `action_id` für Topic-/Gap-/Cluster-Ziele
- stale/legacy Decisions werden sichtbar gemeldet und nie konsumiert
- accepted/rejected/deferred und auto_apply entsprechen der freigegebenen Rechte-Matrix
- jede neue `echte_luecke` erzeugt eine unresolved `real_gap_review`-Aktion
- output-preserving Fehlerpfade und explizite Partial-Metadaten für Evaluator/Innovation
- Human Gate nur für aktuelle unresolved `human_required`-Aktionen
- eindeutige, sequenzielle Innovation-Priorisierung ohne Duplikate
- Erhalt des Reddit-Haupt-Corpus bei null verwendbaren Posts
- offline-sichere Tests; DDG-Smoke-Test nur opt-in

### Konsequenz für die finale Evidenz

Nach Code-Freeze ist ein frischer kontrollierter Lauf mit anschließender neuer Human Review
erforderlich. Erst dessen provenance-gebundene Gap-, Innovation-, Evaluator- und Human-Decision-
Artefakte dürfen für die finale Ergebnisdarstellung verwendet werden. Der nächste fachliche
Schritt ist die kuratierte Prüfung der bestehenden Leistungsreferenz; bestehende generierte
Artefakte wurden in diesem Fix-Schritt bewusst nicht verändert.


## Finaler kontrollierter E2E-Lauf nach Analysis-Encoding-Fix — 13.07.2026

Nach Abschluss der Stabilisierung wurde ein letzter gezielter Downstream-Lauf
mit der reparierten Version des Analysis Agents durchgeführt:

```text
Analysis → Gap Analysis → Innovation → Evaluator → Human Review

Source Discovery, Scraper und Preprocessing wurden nicht erneut ausgeführt,
da der zugrunde liegende Korpus unverändert blieb.

Ausgangsdaten

Der finale Lauf verwendete insgesamt 555 vorverarbeitete Dokumente:

126 Web-Dokumente
361 erhaltene Reddit-Dokumente
68 FragDenStaat-Dokumente

Der aktuelle Reddit-Zugriff blieb extern blockiert. Beim vorherigen vollständigen
E2E-Lauf endeten 10 von 10 Anfragen mit HTTP 403. Der bestehende Korpus mit
361 Datensätzen wurde dabei vollständig erhalten und nicht überschrieben.

Analysis

Der Analysis Agent wurde nach der Reparatur der UTF-8-Kodierung und der
Gemini-Modellkonfiguration erneut ausgeführt.

Ergebnis:

555 analysierte Dokumente
25 Topics
16 relevante Topics
9 irrelevante Topics

Die Analysis-Ausgabe wurde erfolgreich unter
data/analysis/analysis_output.json gespeichert und vom Pipeline-Validator
als technisch valide bestätigt.

Während eines ersten Versuchs antwortete Gemini mit einem temporären
503 UNAVAILABLE aufgrund hoher Modellnachfrage. Der unmittelbar folgende
Wiederholungsversuch war erfolgreich. Dies war eine externe temporäre
Verfügbarkeitsstörung und kein Fehler der lokalen Pipeline.

Gap Analysis

Die Gap Analysis wurde mit dem OpenAI-Backend und gpt-4.1-mini ausgeführt.

Ergebnis:

16 verarbeitete relevante Topics
16 Gap-Einträge
11 Cluster
0 echte Lücken
10 Prozessprobleme
5 Informationslücken
1 bereits abgedecktes Thema
0 irrelevante Einträge
0 Review-Fälle
0 entfernte ungültige Matching Services
10 erfolgreiche Pass-2-Aufrufe
1 übersprungener Cluster

Alle finalen gap.topic_id-Werte entsprechen wieder den kanonischen
Analysis-Topic-IDs. Der zuvor gefundene Fehler, bei dem semantische Werte wie
1_aktenauskunft_... in topic_id geschrieben wurden, trat nicht erneut auf.

Innovation

Der Innovation Agent erzeugte auf Basis der 11 Gap-Cluster:

10 Innovationen
1 übersprungenen bereits abgedeckten Cluster
4 intern markierte Review-Fälle
0 fehlgeschlagene Cluster

Zu den erzeugten Konzepten gehörten unter anderem Assistenten für Elterngeld,
Familiengeld, Kindergeld, Widerspruchsverfahren und Informationsangebote.

Evaluator

Der finale Evaluator-Lauf wurde mit OpenAI und gpt-4.1-mini ausgeführt.

Evaluator Run ID: ER_20260713T232724_c71d27e155
Output status: complete
Failed passes: 0

Ergebnis:

25 Topics evaluiert
16 Gaps in Pass 2 evaluiert
0 Gaps aufgrund fehlender Scope-Zuordnung übersprungen
10 Innovationen evaluiert
7 Innovationen mit Verdict accept
3 Innovationen mit Verdict rework

Evaluator-Aktionen:

9 auto_apply
15 human_required
1 suggestion_only

Nach dem finalen Human Review wurden alle offenen menschlichen Entscheidungen
geschlossen. Es wurde keine weitere Regenerations- oder Discovery-Schleife
gestartet, da die Datengrundlage für den finalen Projektstand eingefroren wurde.

Im Live-Test gefundene und behobene Probleme

Während der kontrollierten Tests wurden mehrere Probleme identifiziert:

Fehlender Import von topic_removals im Gap Agent.
Überschreitung des Groq-TPM-Limits beim kombinierten Gap-Prompt.
Nicht verfügbare ältere Gemini-Modellbezeichnung.
Beschädigte UTF-8-Zeichen im Analysis-Prompt.
Semantische zusammengesetzte Werte in gap.topic_id.
Dadurch verursachtes vollständiges Überspringen aller Gaps in Evaluator
Pass 2.
Temporäre Gemini-Überlastung mit HTTP 503.
Externe Reddit-Blockierung mit HTTP 403.

Die Import-, Encoding- und Topic-ID-Probleme waren lokale Codefehler und wurden
behoben sowie durch Regressionstests abgesichert. TPM-Limits, Modellverfügbarkeit,
Gemini 503 und Reddit 403 waren externe betriebliche Einschränkungen.

Finale technische Validierung

Nach den letzten Codekorrekturen ergab die Offline-Test-Suite:

49 passed, 1 skipped, 2 subtests passed

Zusätzlich wurden bestätigt:

alle Python-Dateien erfolgreich per AST geparst
git diff --check ohne Fehler
keine UTF-8-BOM im Analysis Agent
keine bekannten Mojibake-Zeichen im Analysis-Prompt
keine Änderung an data/reference/existing_services.json
weiterhin 60 kuratierte Services
keine API-Keys oder .env-Dateien in Git
alle Pipeline-Outputs technisch valide
Evaluator vollständig und ohne fehlgeschlagene Passes
alle 16 Gaps erfolgreich in Pass 2 verarbeitet
kein weiterer vollständiger Pipeline-Lauf erforderlich
Fazit

Der finale Lauf bestätigt, dass die stabilisierte Pipeline technisch
funktionsfähig ist und der Human-in-the-Loop-Prozess kontrolliert arbeitet.
Insbesondere wurden stale Entscheidungen nicht auf neue Evaluator-Läufe
übertragen, Agenten nicht automatisch verkettet und bestehende Outputs bei
Client- oder API-Fehlern geschützt.

Der aktuelle Projektstand ist bereit für die abschließende Dokumentation,
den separaten Commit der finalen E2E-Artefakte und die Übergabe zur fachlichen
Bewertung.


Der Abschnitt ergänzt die bisherigen Findings, ohne die ältere Testhistorie zu überschreiben. Die im Codex-Audit dokumentierten Vorher-nachher-Vergleiche und technischen Verbesserungen bleiben damit erhalten. :contentReference[oaicite:0]{index=0}

Vor dem Einfügen prüfe nur noch:

```powershell
& $Py scripts\pipeline_status.py

Steht dort tatsächlich human_offen=0, kann der Text unverändert übernommen werden. Andernfalls den Satz über den abgeschlossenen Human Review erst nach Abschluss der 15 Entscheidungen ergänzen.