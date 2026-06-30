# Runbook: manuelle End-to-End-Pipeline

Dieses Runbook ist die operative Anleitung für Prüfer, Teammitglieder und spätere
Projektarbeit. Die Pipeline hat absichtlich keinen Orchestrator: Menschen starten jede
Stage, prüfen deren Ergebnis und entscheiden nach dem Evaluator über weitere Schritte.

## Grundprinzip

```text
keywords.py
    |
Source Discovery -----> Web Scraper --+
Reddit Scraper ------------------------+--> Preprocessing --> Analysis
FragDenStaat Scraper ------------------+                         |
                                                                 v
existing_services.json ------------------------------------> Gap Analysis
                                                                 |
                                                                 v
                                                            Innovation
                                                                 |
                                                                 v
                                                            Evaluator
                                                                 |
                                                        HUMAN DECISION REQUIRED
```

Die drei Scraper dürfen in beliebiger Reihenfolge oder parallel in getrennten Terminals
laufen. Preprocessing beginnt erst, wenn alle drei Scraper-Outputs valide sind. Alle
späteren Stages sind sequentiell.

`data/reference/existing_services.json` ist eine kuratierte Referenz und regulärer Input,
keine Stage jedes End-to-End-Laufs. `scripts/build_reference.py` und
`scripts/migrate_reference_needs.py` dienen ausschließlich der bewussten Pflege dieser
Referenz.

## Vorbereitung

Vom Repository-Root aus:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Für Analysis wird `GEMINI_API_KEY`, für Gap Analysis, Innovation und Evaluator
`GROQ_API_KEY` benötigt. Source Discovery und Scraper benötigen Netzwerkzugriff.

Vorhandene JSON-Dateien sind kuratierte Demo-Artefakte. Der Status-Checker kann ihre
Struktur prüfen, aber nicht behaupten, dass sie im aktuellen Arbeitslauf entstanden sind.
Für einen echten Neu-Lauf die gewünschte Stage bewusst ausführen; sie überschreibt ihren
regulären Output.

## Status und Validierung

```bash
python scripts/pipeline_status.py
python scripts/pipeline_status.py --stage preprocessing
python scripts/pipeline_status.py --json
```

| Status | Bedeutung |
|---|---|
| `READY` | Alle Inputs sind valide, der Output fehlt; Stage kann manuell starten. |
| `BLOCKED` | Mindestens ein Input fehlt oder ist strukturell ungültig. |
| `OUTPUT VALID` | Output ist lesbares, nichtleeres JSON mit den erwarteten Pflichtfeldern. |
| `OUTPUT INVALID` | Output existiert, verletzt aber den technischen Vertrag. |

Exit-Code `0` bedeutet, dass alle ausgewählten Outputs technisch valide sind. Exit-Code
`1` bedeutet, dass mindestens eine Stage bereit, blockiert oder ungültig ist. Die Prüfung
bewertet keine fachliche Qualität, startet keinen Agent und schreibt keine Datei.

## Stages

| Stage | Befehl | Inputs | Output | Technisches Erfolgskriterium |
|---|---|---|---|---|
| Source Discovery | `python -m agents.source_discovery_agent` | `config/keywords.py` | `data/raw/sources.json` | Nichtleere JSON-Liste |
| Web Scraper | `python -m agents.scraping_agents.webscraping_agent` | `data/raw/sources.json` | `data/raw/scraped_web.json` | Nichtleere JSON-Liste |
| Reddit Scraper | `python -m agents.scraping_agents.reddit_scraper` | `config/keywords.py` | `data/raw/scraped_reddit.json` | Nichtleere JSON-Liste; ein 403-Partial gilt nicht als regulärer Erfolg |
| FragDenStaat Scraper | `python -m agents.scraping_agents.fragdenstaat_scraper` | interne Suchkonfiguration | `data/raw/scraped_fragdenstaat.json` | Nichtleere JSON-Liste |
| Preprocessing | `python -m agents.preprocessing` | alle drei Scraper-Outputs | `data/preprocessed/preprocessed.json` | Nichtleere JSON-Liste |
| Analysis | `python -m agents.analysis_agent` | Preprocessing-Output | `data/analysis/analysis_output.json` | Topics, Sentiments und Interpretation vorhanden |
| Gap Analysis | `python -m agents.gap_analysis_agent` | Analysis + Referenz | `data/gap_analysis/gap_analysis_output_v2.json` | Nichtleere `gaps`-Liste; `review_count` prüfen |
| Innovation | `python -m agents.innovation_agent` | Gap v2 + Referenz | `data/innovation/innovation_output.json` | Nichtleere `innovations`-Liste; `review_count` prüfen |
| Evaluator | `python -m agents.evaluator_agent` | Analysis + Gap v2 + Innovation + Referenz + optionale Metriken | `data/evaluation/evaluator_output.json` | Evaluation-Sektionen und Aktionslisten vorhanden |

Nach jeder Stage:

1. Prozess-Exit-Code und Konsolenausgabe auf Fehler prüfen.
2. `python scripts/pipeline_status.py --stage <stage>` ausführen.
3. Größen, Review-Zähler und fachlich auffällige Stichproben im Output prüfen.
4. Erst dann die nächste Stage starten.

`OUTPUT VALID` ist eine strukturelle Mindestprüfung. Ein LLM-Output mit schwachen oder
unplausiblen Aussagen kann trotzdem strukturell valide sein.

## Human-in-the-Loop nach dem Evaluator

Nach einem validen Evaluator-Output immer `review_count`, `review_reasons`,
`aggregierte_aktionen`, `rework_warteschlange`, `keyword_feedback`, `priorisierung` und
`konvergenz_status` lesen. Sind Reviews oder Aktionen offen, zeigt der Status-Checker
`HUMAN DECISION REQUIRED`. Das ist ein beabsichtigter Übergabepunkt, kein Pipeline-Fehler.

Das Terminal-Review kann für alle Aktionen oder gezielt für einen Bereich gestartet werden:

```bash
python scripts/review_evaluator.py
python scripts/review_evaluator.py --section keywords
```

Für jede Empfehlung wird `akzeptiert`, `abgelehnt` oder `vertagt` erfasst. Das Ergebnis liegt
in `data/evaluation/human_decisions.json`; spätere Review-Sitzungen ergänzen beziehungsweise
aktualisieren bestehende Entscheidungen. Es wird keine Stage automatisch gestartet.

| Evaluator-Signal | Menschliche Entscheidung | Betroffene Wiederholung |
|---|---|---|
| `regenerieren` | Rework-Briefing prüfen und entscheiden, ob Gap-Basis, Träger, Integrationspunkt oder Idee geändert werden muss. | Ursache im Gap-/Referenz-Input oder in der Agent-Logik korrigieren; danach Innovation und Evaluator erneut starten. |
| `reklassifizieren` | Vorgeschlagene Klassifikation gegen Topic, Evidenz und Referenz bestätigen oder ablehnen. | Klassifikationsursache im Gap-Input bzw. Gap Agent korrigieren; danach Gap Analysis, Innovation und Evaluator erneut starten. |
| `topics_entfernen` | Bestätigen, dass es sich um Noise oder Out-of-Scope-Inhalt handelt. | Filter-/Analyseursache korrigieren; ab der betroffenen früheren Stage neu laufen lassen. |
| `konvergenz_zusammenfuehren` | Ähnliche Ideen vergleichen und eine führende Lösung oder klare Abgrenzung wählen. | Innovationslogik/-input anpassen; Innovation und Evaluator erneut starten. |
| `schwache_keywords` | Nicht automatisch löschen; anhand Quellen und Topics prüfen, ob das Keyword überwiegend Noise liefert. | Bei bestätigter Änderung neuer Lauf ab Source Discovery. |
| `neue_keywords_vorgeschlagen` | Nutzen, Scope und erwartbare Quellen prüfen; nur bewusst in `config/keywords.py` übernehmen. | Neuer Lauf ab Source Discovery. |

Akzeptierte Keyword-Ergänzungen und -Entfernungen werden beim nächsten manuell gestarteten
Source-Discovery- und Reddit-Lauf angewendet. Die Seed-Liste bleibt unverändert und die
menschliche Entscheidung ist im JSON nachvollziehbar.

Die übrigen Listen sind aktuell **beratende Outputs**. Gap- und Innovation-Agent lesen
Rework-, Remove-, Reclassify- und Merge-Entscheidungen noch nicht ein. Ein bloßes erneutes Ausführen
mit unveränderten Inputs löst eine Aktion deshalb nicht zuverlässig. Änderungen an
generierten JSON-Dateien sind keine dauerhafte Lösung: Sie sind nicht reproduzierbar und
werden beim nächsten Lauf überschrieben. Stattdessen wird die Ursache in Konfiguration,
Referenz, Input oder Agent-Logik korrigiert und die kleinste betroffene Teilpipeline
manuell neu ausgeführt.

Der Mensch übernimmt damit explizit Aufgaben, die ein Orchestrator automatisieren würde:
Routing, Freigabe, Auswahl des Wiederanlaufpunkts, Retry-Entscheidung, Keyword-Änderung und
Abbruch bei fehlender Konvergenz.

## Typische Fehler

- **API-Key fehlt:** `.env` prüfen; nur die LLM-Stages benötigen Keys.
- **Web 403/404 oder robots.txt-Skip:** Einzelne Skips sind normal; Output-Größe und Logs prüfen.
- **Reddit 403:** Ein Partial-Output ist kein erfolgreicher vollständiger Lauf.
- **Leerer Output:** Stage gilt als fehlgeschlagen, auch bei syntaktisch korrektem JSON.
- **Metrics partial/missing:** Evaluator läuft defensiv weiter; `source_stats_status` prüfen.
- **Review-Zähler größer null:** Kein technischer Abbruch, aber fachliche Freigabe erforderlich.

## Abschlusscheck

Ein Lauf ist abgeschlossen, wenn der Status-Checker alle Outputs als valide meldet, keine
ungeklärten Reviews verbleiben, alle Aktionen umgesetzt oder begründet verworfen wurden
und die priorisierten Innovationen fachlich freigegeben sind. Die Entscheidung wird in
den Projekt-/Thesis-Notizen festgehalten; dieses Runbook führt keine State-Datei ein.
