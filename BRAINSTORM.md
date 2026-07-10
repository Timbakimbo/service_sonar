# Service Sonar – Brainstorm & Offene Fragen

## Offene Fragen

### BERTopic Output
- [ ] 25 Topics ist über Zielbereich (8-15) — Evaluator muss konsolidieren
- [ ] Redundante Elterngeld-Topics (5, 9, 11, 23) zusammenführen
- [ ] Sprach-Noise Topics (4, 6, 12, 13) als irrelevant markieren
- [ ] Behörden-Boilerplate Topics (8, 18) als irrelevant markieren

### Quellen-Strategie
- [x] Evaluator schlägt schwache/neue Keywords vor; Mensch entscheidet im Terminal-Review
- [ ] Qualität der akzeptierten Keyword-Änderungen im nächsten vollständigen Lauf messen
- [ ] Min 1 Wort in Web Scraper durchgekommen — Content Filter noch nicht wasserdicht

### Redundanz & Relevanzsignal
- [ ] Semantische Redundanz: Embedding-Ähnlichkeit zwischen Topics — ab welchem Threshold zusammenführen?
- [ ] Relevanzsignal Kombination:
  - Häufigkeit (BERTopic Topic-Gewicht)
  - Negativem Sentiment
  - Reddit Score + num_comments
- [ ] Genaue Gewichtung erst nach erstem vollständigem Durchlauf entscheidbar

### Feedback Loop
- [x] Evaluator liefert qualitative schwache/neue Keywords
- [x] Human Review speichert accept/reject/defer file-basiert
- [x] Discovery und Reddit wenden akzeptierte Keyword-Entscheidungen im nächsten manuellen Lauf an
- [ ] Quantitativ messen, ob akzeptierte Keywords Relevanz und Themenabdeckung verbessern
- [ ] Bereits gescrapter Content bleibt — kein Re-Scraping für alte Keywords
- [ ] Rework-/Reclassify-/Merge-Entscheidungen als optionale Inputs der Fach-Agents umsetzen

### Datenbank
- [ ] Phase 1: JSON reicht für Prototyp
- [ ] Phase 2: SQLite wenn Datenmenge es erfordert — wann genau switchen?

### Agents vs. Hardcoded
- [ ] Genaue Tool-Definition für echte Agents noch offen
- [ ] Wie testen wir ob der Keyword Agent sinnvolle Entscheidungen trifft?
- [ ] Konzept "Analysis Agent passt BERTopic Parameter selbst an" — für nächste Iteration

### Gap Analysis Qualität
- [ ] Warum klassifiziert der Gap Analysis Agent aktuell nahezu alle Topics als Prozessproblem oder Informationslücke?
- [ ] Werden echte Versorgungslücken durch allgemeine Beratungsangebote überschattet?
- [ ] Ab wann gilt eine Beratungsleistung als tatsächliche Bedarfsabdeckung?
- [ ] Braucht der Gap Analysis Agent einen vorgeschalteten semantischen Retriever statt reinem LLM-Matching?
- [ ] Soll der Evaluator Agent Gap-Klassifizierungen nachträglich prüfen und korrigieren?
- [ ] Welche Kriterien rechtfertigen formal die Klasse `echte_luecke`?

## Getroffene Entscheidungen

### Architektur — Agent vs. Hardcoded Pipeline
Bewusste Entscheidung: Agents nur wo Reasoning nötig ist, hardcoded wo Regeln ausreichen.

**Hardcoded Module:**
- Source Discovery — arbeitet Keywords deterministisch ab
- Web Scraper — klare Regeln, deterministisch
- Reddit Scraper — Public JSON Endpoints, deterministisch
- FragdenStaat Scraper — öffentliche API, deterministisch, inkrementell
- Preprocessing — deterministisch, spaCy

**Echter Agent (LLM Reasoning Layer):**
- Analysis Agent → Gemini 2.5 Flash
- Gap Analysis Agent → Groq (`llama-3.3-70b-versatile`)
- Innovation Agent → Groq (`llama-3.3-70b-versatile`)
- Evaluator Agent → Groq (`llama-3.3-70b-versatile`), 4-Pass-Kaskade
- Keyword-Feedback → Evaluator-Urteil + menschliche Freigabe, kein separater Agent nötig

### Modell-Strategie
- Analysis Agent → Gemini 2.5 Flash
- Gap Analysis Agent → Groq `llama-3.3-70b-versatile`
- Build Reference nutzt Gemini zur Extraktion bestehender Leistungen
- Komplexere Aufgaben → günstige paid Modelle möglich (Claude Haiku, DeepSeek, Groq)
- Kein Sonnet nötig — bewusste Kostenstrategie
- Qualitätsziel: erst funktionierende Pipeline, danach gezieltes Modell-Upgrade falls nötig

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

### Orchestrierung — Entscheidung: KEIN zentraler Orchestrator
- Plain Python, kein Framework
- Jeder Agent/Modul = eigene Python-Datei, Single Responsibility
- **Bewusst gegen einen zentralen Orchestrator entschieden.** Begründung: Inter-Agent-Kommunikation
  läuft file-basiert über die JSON-Outputs jeder Stufe; Loop-Control übernimmt der Evaluator via
  Action-Listen (`aggregierte_aktionen`) + Human-in-the-Loop. Ein zentraler Orchestrator würde
  diesem Architektur-Konzept widersprechen.
- Stufen werden vorerst manuell in Reihenfolge ausgeführt (siehe README „Local Run Sequence").

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

### Reference Builder — bestehende Leistungen
- Zweck: Aufbau von `data/reference/existing_services.json` als Referenz für den Gap Analysis Agent
- Quelle: gescrapte Web-Dokumente mit offiziellen, kommunalen, freien und privaten Angeboten
- Ursprünglich war ein Migrationsskript geplant
- Tatsächliche Entscheidung: alte `existing_services.json` gelöscht und durch angepasste Build-Reference Pipeline neu erzeugt
- Ergebnis: 77 bestehende Leistungen im deutschen v2-Schema
- Schema enthält u.a.:
  - `name`
  - `beschreibung`
  - `zielgruppe`
  - `zustaendige_stelle`
  - `leistungsart`
  - `ebene`
  - `abgedeckte_bedarfe`
  - `zugangsvoraussetzungen`
  - `antragskanaele`
  - `bekannte_prozessrisiken`
  - `quellen_urls`
  - `konfidenz`
- Beratungen und Rechtsansprüche gelten ausdrücklich als Leistungen, nicht nur Geldleistungen
- Private Angebote werden dokumentiert, dürfen aber im Gap Agent nicht als vollwertige staatliche Bedarfsabdeckung zählen

### Gap Analysis Agent — aktueller Stand
- Gap Analysis Agent implementiert
- Input:
  - `data/analysis/analysis_output.json`
  - `data/reference/existing_services.json`
- Output:
  - `data/gap_analysis/gap_analysis_output.json`
- Backend:
  - Groq API
  - `llama-3.3-70b-versatile`
- Klassifizierung:
  - `echte_luecke`
  - `prozessproblem`
  - `informationsluecke`
  - `bereits_abgedeckt`
  - `irrelevant`
- Ein einziger Groq-Call für alle relevanten Topics
- Topic-IDs werden string-normalisiert, da BERTopic teilweise Integer und JSON Sentiments String-Keys erzeugt
- JSON Parsing wurde robuster gemacht
- `max_tokens` ergänzt, damit der Output nicht abgeschnitten wird
- Zusammenfassung der Klassifikationen wird im Output gespeichert

### Gap Analysis — Qualitätssicherung
- Matching Services dürfen nur noch exakte Namen aus `existing_services.json` sein
- Post-Validation entfernt halluzinierte Matching Services
- Ungültige Behörden-/Trägernamen wie Familienkasse, Gesundheitsamt oder Krankenkasse werden nicht als Leistung akzeptiert
- `needs_review` Flag markiert unsichere Fälle
- `confidence` Feld pro Gap ergänzt
- Review-Fälle werden im Output gezählt
- Entfernte ungültige Matching Services werden als Kennzahl gespeichert

### Gap Analysis — bisherige Beobachtung
- Erster stabiler Lauf:
  - 15 relevante Topics
  - 77 Referenzleistungen
  - 11 Prozessprobleme
  - 4 Informationslücken
  - 0 echte Lücken
  - 0 bereits abgedeckt
  - 0 irrelevant
  - 1 Review-Fall
  - 1 entfernter ungültiger Matching Service
- Ergebnis ist technisch stabil, aber fachlich noch nicht final validiert
- Hauptproblem: Service-Matching ist semantisch noch zu grob
- Beispiele problematischer Matches:
  - Aufenthaltsrecht/Migration → Bayerisches Familiengeld / Elterngeld
  - gesundheitliche Herausforderungen → Kinderkrankengeld / Mutterschaftsgeld
- Erkenntnis: Der schwierigste Teil ist nicht mehr Topic-Erkennung, sondern korrektes Mapping von Bürgerproblemen auf bestehende Leistungen

### Gap Analysis Agent v2 — Entscheidungen
- **2-Pass-Architektur** statt 1-Call: Pass 1 strukturiert (Klassifikation, Phase, cluster_id, matching), Pass 2 generiert pro Cluster EINE konkrete Empfehlung. Trennung erzwingt Konkretheit, verhindert Boilerplate.
- **Deterministisches Clustering statt LLM-Clustering**: LLM-Cluster-Labels sind run-instabil (Llama kodierte Facette statt Leistung in cluster_id, auch nach Prompt-Schärfung). Konsolidierung im Code über dominanten matching_service; restriktive Regel (gleicher Service + gleiche Klassifizierung + kein blockierender Review-Grund), sonst solo_<id>. LLM-Label bleibt als cluster_id_llm.
- **Neue Felder**: customer_journey_phase (kontrolliertes Vokabular), cluster_id, cluster_zusammenfassung. schema_version 1.2-de, neuer Output-Pfad (alte Datei bleibt zum Vergleich).
- **Generic-Detection** (lightweight, keine Dependency) flaggt Boilerplate-Empfehlungen via Phrasen + Spezifik-Heuristik; Leistungsnamen zählen NICHT als Spezifik.

### Innovation Agent — Entscheidungen
- 1 Call pro relevantem Cluster → genau EINE Innovation pro Cluster.
- **Determinismus-Split**: Fakten (Topics, Leistungen, Phasen, Klassifizierung) setzt der Code, nur kreative Substanz kommt vom LLM — Grounding gegen Halluzination.
- **innovation_typ Coerce statt Flag-only**: bei Mismatch zur klassifizierung wird auf ersten erlaubten Typ gesetzt, Original in innovation_typ_original, needs_review bleibt.
- **Titel-Schranke: Zeichen statt Wörter** (20–80) — Wort-Untergrenze (min 5) flaggte 10/10 wegen deutscher Komposita-Titel. Empirisch korrigiert auf Zeichen-Cap.
- **Träger-Whitelist**: Alias-Map (Vollname ↔ Abkürzung) + kuratierte öffentliche Träger. L-Bank (BW) ausgeschlossen — kein bayerischer Träger.

### Evaluator Agent — Entscheidungen
- **4-Pass-Kaskade**: Topics → Gaps (gated auf in_scope) → Innovationen (cross-pass) → Aggregation. Pässe abhängig, spätere nutzen frühere als Kontext.
- **Determinismus-Split**: evaluation_ids, aggregierte_aktionen, Cross-Pass-Override, priorisierung-Vollständigkeit (deterministisch_angehaengt-Flag), Konvergenz-Normalisierung (Token-Sort) im Code. Plausibilität/Begründungen/Briefings im LLM.
- **Pass 1 bewertet alle 28 Topics** (nicht nur die 15 relevanten) → kann Analysis-Agent-Entscheidung überstimmen (false-positives UND false-negatives).
- **noise vs out-of-scope strikt getrennt**: noise=technisches Crawling-Artefakt; in_scope=false ohne noise=kohärentes Topic außerhalb Familienscope. Beide → remove, aber unterscheidbare Begründung.
- **Plausibilitäts-Overrides** (Code): traeger_domain_plausibel=false oder integrationspunkte_plausibel=false bei accept → rework. Fangen NUR innere Inkonsistenz, nicht falsch-positive Flag-Werte.
- **source_stats defensiv aus metrics.json**: list-of-runs (partial) / dict (complete) / missing — robust gegen spätere save_metrics-Erweiterung.

### Manueller End-to-End-Betrieb — Entscheidungen
- **RUNBOOK als operative Single Source of Truth**: `README.md` bleibt Quickstart; `RUNBOOK.md`
  dokumentiert Reihenfolge, Inputs, Outputs, Erfolgskriterien, Fehlerbilder und Human-Handoff.
- **Read-only Status statt Runner**: `scripts/pipeline_status.py` liest ausschließlich bestehende
  JSON-Artefakte. Status: `READY`, `BLOCKED`, `OUTPUT VALID`, `OUTPUT INVALID`; optional pro Stage
  oder als JSON. Das Script startet keine Agents und persistiert keinen Zustand.
- **Human Gate explizit sichtbar**: Reviews, `aggregierte_aktionen` und Keyword-Feedback führen zu
  `HUMAN DECISION REQUIRED`, nicht zu automatischer Weiterleitung oder Re-Generation.
- **JSON-Dateien bleiben die Wahrheit**: keine Run-State-Datei, Datenbank, Queue oder versteckte
  Fortschrittslogik. Vorhandene Demo-Outputs können strukturell valide sein, ohne aus dem aktuellen
  Lauf zu stammen; das wird ausdrücklich dokumentiert.
- **Evaluator-Rechte-Matrix statt HIL für alles**: Aktionen werden in `auto_apply`,
  `human_required` und `suggestion_only` getrennt. Low-risk-Topic-Removals und sichere
  Gap-Reklassifikationen dürfen automatisch in den nächsten manuellen Stage-Lauf eingehen;
  Keywords und Innovationen bleiben Human-Gate.
- **Human-Review als Terminal-UI**: `scripts/review_evaluator.py` erfasst accept/reject/defer in
  `data/evaluation/human_decisions.json`. Mehrere bereichsweise Reviews werden zusammengeführt.
- **Geschlossener Feedback-Slice erweitert**: Source Discovery und Reddit lesen akzeptierte
  Keyword-Add/Remove-Entscheidungen; Gap Analysis liest Topic-Remove und Gap-Reclassify;
  Innovation liest Rework-Briefings und Merge-Gruppen. Seeds bleiben unverändert; kein
  automatischer Start und kein Auto-Loop.
- **Technische vs. fachliche Validität getrennt**: Der Checker prüft JSON-Typ, Pflichtfelder und
  nichtleere Kerndaten. Fachliche Plausibilität bleibt menschliche Aufgabe.

### E2E-Testlauf 30.06.2026 — neue Entscheidungen
- **Vorwärtslauf verifiziert**: 25 wirksame Keywords → 207 akzeptierte Quellen → 575 Dokumente
  → 26 Topics → 17 relevante Topics → 9 Gap-Cluster → 9 Innovationen → Evaluator ohne Pass-Fehler.
- **Evaluator-Ergebnis**: 5 Innovationen akzeptiert, 4 Rework; zusätzlich 3 Reclassify-,
  9 Topic-Remove- und 2 Merge-Vorschläge.
- **Human-Review funktioniert**: Keyword-, Topic- und Merge-Entscheidungen wurden im Terminal
  akzeptiert oder vertagt und in `human_decisions.json` gespeichert.
- **Keyword-Learning**: `ZBFS` als Removal akzeptiert, nachdem der Web-Run fachfremde Treffer zu
  „zeroing barrier functions“ erzeugte. Generische neue Keywords wie `Kinderbetreuung` erzeugen
  ebenfalls Noise; Vorschläge brauchen Bayern-/Problemkontext, nicht nur Human-Freigabe.
- **Robustheit verifiziert**: Reddit lieferte 55/55-mal 403; der bestehende 361-Post-Datensatz
  blieb erhalten. FragDenStaat deduplizierte 68 bestehende Anfragen. `source_stats=complete`.
- **Rechte-Matrix implementiert**: Der Evaluator schreibt normalisierte `aktionen` mit
  Autonomie-Stufe, Confidence und Risiko. `review_evaluator.py` zeigt standardmäßig nur
  `human_required`; Auto-/Suggestion-Actions sind optional inspizierbar.
- **Reddit-Blocked sichtbar**: 403-Runs werden nicht mehr nur als valider alter Corpus
  getarnt. Metrics und `pipeline_status.py` unterscheiden `OUTPUT VALID`, `STALE` und
  `BLOCKED`.

### Modell-Strategie — Update nach Evaluator-Tuning
- Prompt-Schärfung wirkt zuverlässig bei Konvergenz-Erkennung (Pattern-Labeling) und Noise/out-of-scope-Trennung mit Llama 3.3.
- **Vorgemerkter Gemini-Fall**: Pass-3-Integrationspunkte-Plausibilität bei Grenzfällen (z.B. INN_009 ElternGuide — BayernID bei personalisierter vs. niedrigschwelliger Beratung). Llama setzt hier den Flag falsch-positiv; das ist eine Urteils-Schwäche, die Prompt-Text nicht löst und Code-Overrides nicht korrigieren können.

## Nächste Schritte
- [x] Content Filter Source Discovery ✅
- [x] Content Filter Web Scraper ✅
- [x] Run 1 + Run 2 Metrics ✅
- [x] Reddit Scraper ✅
- [x] FragdenStaat Scraper (ZBFS + Familienkasse + StMAS) ✅
- [x] Preprocessing Modul ✅
- [x] Analysis Agent inkl. BERTopic Tuning ✅
- [x] Reference Builder / existing_services.json ✅
- [x] Gap Analysis Agent (Groq + Llama 3.3 70B) ✅
- [x] Matching Validation gegen Referenzdatenbank ✅
- [x] needs_review + Confidence Scores ✅
- [x] FINDINGS.md + BRAINSTORM.md ins Repo legen (für Claude Code Kontext)
- [x] Präsentationsstand dokumentieren ✅
- [ ] Min-Wörter Bug in Web Scraper fixen (1 Wort durch Filter)
- [ ] Qualität des Service-Matchings verbessern
- [ ] Semantische Service-Suche / Retrieval vor Gap Analysis prüfen
- [ ] Echte-Lücke-Kriterien schärfen
- [x] Gap Analysis Agent v2 (2-Pass + deterministisches Clustering) ✅
- [x] Service Innovation Agent ✅
- [x] Evaluator Agent (4-Pass-Kaskade) ✅
- [x] Deutsches End-to-End-RUNBOOK + README-Quickstart ✅
- [x] Read-only Pipeline-Status und strukturelle Stage-Validierung ✅
- [x] Human-in-the-Loop-Aktionsmatrix nach dem Evaluator ✅
- [x] Terminal-Review mit accept/reject/defer und persistierten Human Decisions ✅
- [x] Akzeptierte Keyword-Entscheidungen in Discovery und Reddit wirksam machen ✅
- [x] Vollständigen manuellen E2E-Testlauf anhand des RUNBOOK durchführen und protokollieren ✅
- [x] Entscheiden, wie bestätigtes Evaluator-Feedback reproduzierbar als manueller Agent-Input dient
      (ohne Auto-Loop und ohne Orchestrator) ✅
- [x] Per-Source-Metriken bis `source_stats=complete` im Evaluator verifiziert ✅
- [ ] Gemini-Test für Pass-3-Integrationspunkte-Plausibilität (Grenzfälle wie INN_009)
- [x] Keyword-Feedback-Loop als Human-in-the-Loop-Vertical-Slice ✅
- [x] Fachagenten konsumieren akzeptierte/Auto-Apply Topic-/Gap-/Innovation-Aktionen ✅
- [x] Evaluator-Rechte-Matrix (`auto_apply`, `human_required`, `suggestion_only`) ✅
- [x] Reddit Blocked/Stale in Metrics und Status sichtbar machen ✅
- [x] ~~Orchestrator~~ — bewusst verworfen (file-basiert + Evaluator-Action-Listen + Human-in-the-Loop)
- [ ] Umbenennung: nicht-Agent Module aus `agents/` Ordner raus, neuer `modules/` Ordner
