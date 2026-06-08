"""
Gap Analysis Agent: Identifiziert echte Bedarfslücken aus den relevanten Topics
 des Analysis Agents durch Abgleich mit der Referenz bestehender Leistungen.

Input:
- data/analysis/analysis_output.json (Analysis Agent Output)
- data/reference/existing_services.json (Referenz bestehender Leistungen v2-de)

Output:
- data/gap_analysis/gap_analysis_output.json

Klassifizierung pro Topic:
- echte_luecke: keine bestehende Leistung deckt den Bedarf ab
- prozessproblem: Leistung existiert, aber bekannte Prozessrisiken passen zum Topic
- informationsluecke: Leistung existiert, aber Bürger scheinen sie nicht zu kennen
- bereits_abgedeckt: Leistung existiert und deckt den Bedarf sauber ab
- irrelevant: Topic ist nicht thematisch passend für Familienleistungen

Backend: Groq (Llama 3.3 70B). Ein einziger Call für alle Topics — spart API-Quota
und LLM kann holistisch über alle Topics reasonen.

Wichtige Robustheitsmaßnahmen:
- Topic-IDs werden konsistent als Strings behandelt.
- Matching Services werden nach dem LLM-Call gegen echte Referenznamen validiert.
- Erfundenes Matching wie "Familienkasse", "Gesundheitsamt", "Krankenkasse" wird entfernt.
- Wenn die Klassifizierung eine passende Leistung voraussetzt, aber nach Validierung keine
  valide Leistung übrig bleibt, wird needs_review=True gesetzt.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

ANALYSIS_PATH = Path("data/analysis/analysis_output.json")
REFERENCE_PATH = Path("data/reference/existing_services.json")
OUTPUT_PATH = Path("data/gap_analysis/gap_analysis_output.json")

MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 6000

VALID_CLASSIFICATIONS = {
    "echte_luecke",
    "prozessproblem",
    "informationsluecke",
    "bereits_abgedeckt",
    "irrelevant",
}

# Begriffe, die häufig fälschlich als Leistung ausgegeben werden, aber Träger/Behörden/Kanäle sind.
INVALID_MATCHING_TERMS = {
    "familienkasse",
    "gesundheitsamt",
    "krankenkasse",
    "krankenkassen",
    "jobcenter",
    "sozialamt",
    "jugendamt",
    "finanzamt",
    "arbeitgeber",
    "sozialgericht",
    "elterngeldstelle",
    "beratungsstelle",
    "behörde",
    "behoerde",
}

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("GROQ_API_KEY fehlt in .env")

client = Groq(api_key=api_key)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_topics_block(analysis: dict) -> str:
    """
    Baut den Topics-Block für das LLM — nur relevante Topics mit
    Kernproblem und Sentiment-Verteilung.
    """
    interpretation = analysis.get("llm_interpretation", {})
    relevant_topics = interpretation.get("relevant_topics", [])
    topic_overview = {str(t.get("Topic")): t for t in analysis.get("topic_overview", [])}
    topic_sentiments = {str(k): v for k, v in analysis.get("topic_sentiments", {}).items()}

    block = ""
    for rt in relevant_topics:
        tid = str(rt.get("topic_id"))
        overview = topic_overview.get(tid, {})
        sentiment = topic_sentiments.get(tid, {})

        block += f"\n--- Topic {tid} ---\n"
        block += f"Name: {overview.get('Name', '')}\n"
        block += f"Anzahl Dokumente: {overview.get('Count', 0)}\n"
        block += f"Kernproblem: {rt.get('kernproblem', '')}\n"
        block += f"Sentiment-Verteilung: {sentiment}\n"
    return block


def build_services_block(reference: dict) -> str:
    """
    Kompakte Übersicht aller bestehenden Leistungen für den LLM-Kontext.
    Wichtig: Der Name am Anfang ist der einzige gültige Wert für matching_services.
    """
    services = reference.get("services", [])
    block = ""
    for s in services:
        name = s.get("name", "")
        body = s.get("zustaendige_stelle", "")
        kind = s.get("leistungsart", "")
        level = s.get("ebene", "")
        needs = s.get("abgedeckte_bedarfe", [])
        risks = s.get("bekannte_prozessrisiken", [])

        block += f"\n- LEISTUNGSNAME: {name}\n"
        block += f"  Zuständige Stelle: {body}\n"
        block += f"  Leistungsart: {kind}\n"
        block += f"  Ebene: {level}\n"
        block += f"  Bedarfe: {needs}\n"
        block += f"  Prozessrisiken: {risks}\n"
    return block


def parse_json_response(content: str) -> dict:
    """
    Robustes JSON-Parsing — entfernt Markdown-Fences falls Llama sie
    trotz response_format mitsendet.
    """
    content = content.strip()
    content = content.replace("```json", "").replace("```", "").strip()
    return json.loads(content)


def get_valid_service_names(reference: dict) -> set[str]:
    return {
        str(service.get("name", "")).strip()
        for service in reference.get("services", [])
        if str(service.get("name", "")).strip()
    }


def validate_and_normalize_gaps(result: dict, reference: dict, expected_topic_ids: set[str]) -> dict:
    """
    Entfernt erfundene matching_services und markiert Review-Fälle.

    Warum nötig?
    LLMs geben gern Trägernamen oder allgemeine Begriffe als matching_services aus,
    obwohl im Prompt exakte Referenznamen verlangt werden. Dieser Schritt erzwingt
    echte Konsistenz mit existing_services.json.
    """
    valid_service_names = get_valid_service_names(reference)
    valid_lookup = {name.lower(): name for name in valid_service_names}

    normalized_gaps = []
    for raw_gap in result.get("gaps", []):
        gap = dict(raw_gap)
        gap["topic_id"] = str(gap.get("topic_id", "")).strip()

        cls = str(gap.get("klassifizierung", "")).strip()
        if cls not in VALID_CLASSIFICATIONS:
            gap["klassifizierung_original"] = cls
            gap["klassifizierung"] = "irrelevant"
            gap["needs_review"] = True
            gap["review_reason"] = "ungueltige_klassifizierung"
        else:
            gap["klassifizierung"] = cls

        raw_matches = gap.get("matching_services", [])
        if not isinstance(raw_matches, list):
            raw_matches = []

        valid_matches = []
        removed_matches = []

        for match in raw_matches:
            match_str = str(match).strip()
            if not match_str:
                continue

            match_lower = match_str.lower()

            # Harte Entfernung typischer Träger-/Behördenbegriffe.
            if match_lower in INVALID_MATCHING_TERMS:
                removed_matches.append(match_str)
                continue

            # Exakter Match.
            if match_str in valid_service_names:
                valid_matches.append(match_str)
                continue

            # Case-insensitive exakter Match.
            if match_lower in valid_lookup:
                valid_matches.append(valid_lookup[match_lower])
                continue

            # Kein exakter Referenzname: entfernen.
            removed_matches.append(match_str)

        # Reihenfolge beibehalten, Duplikate entfernen.
        seen = set()
        deduped_valid_matches = []
        for name in valid_matches:
            if name not in seen:
                deduped_valid_matches.append(name)
                seen.add(name)

        gap["matching_services"] = deduped_valid_matches
        if removed_matches:
            gap["removed_invalid_matching_services"] = removed_matches

        needs_review_reasons = []

        if gap["topic_id"] not in expected_topic_ids:
            needs_review_reasons.append("unerwartete_topic_id")

        # Diese Klassen setzen logisch meistens voraus, dass mindestens eine echte Leistung matcht.
        if gap.get("klassifizierung") in {"prozessproblem", "informationsluecke", "bereits_abgedeckt"}:
            if not deduped_valid_matches:
                needs_review_reasons.append("klassifizierung_setzt_leistung_voraus_aber_keine_valide_leistung_gematcht")

        # Echte Lücke mit validen Matches ist nicht unmöglich, aber erklärungsbedürftig.
        if gap.get("klassifizierung") == "echte_luecke" and deduped_valid_matches:
            needs_review_reasons.append("echte_luecke_trotz_valider_matching_services")

        # Topic 0 / Migrations- und Aufenthaltsrecht ist oft außerhalb des engen Familienleistungs-Scopes.
        # Nicht automatisch umklassifizieren, aber markieren, falls komisch gematcht.
        problem_text = str(gap.get("kernproblem", "")).lower()
        if "aufenthalt" in problem_text or "migrationshintergrund" in problem_text:
            needs_review_reasons.append("moeglicherweise_ausserhalb_familienleistungs_scope")

        if needs_review_reasons:
            gap["needs_review"] = True
            gap["review_reason"] = ";".join(needs_review_reasons)
        else:
            gap["needs_review"] = False
            gap["review_reason"] = ""

        # Fallbacks für optionale Felder.
        gap.setdefault("prioritaet", 0)
        gap.setdefault("confidence", 0.0)
        gap.setdefault("empfehlung_innovation", "")
        gap.setdefault("begruendung", "")
        gap.setdefault("kernproblem", "")

        normalized_gaps.append(gap)

    result["gaps"] = normalized_gaps
    return result


def run_gap_analysis(analysis: dict, reference: dict) -> dict:
    """
    Ein Groq-Call für alle relevanten Topics. LLM klassifiziert pro Topic.
    """
    topics_block = build_topics_block(analysis)
    services_block = build_services_block(reference)

    prompt = f"""Du bist der Gap Analysis Agent eines Service Sonar für familienbezogene Sozialleistungen in Bayern.

Deine Aufgabe:
Für JEDES relevante Topic aus dem Analysis Agent entscheidest du, ob das Topic eine echte Bedarfslücke ist
oder ob bestehende Leistungen den Bedarf bereits grundsätzlich abdecken.

Du bekommst:
1. relevante Topics mit Kernproblem, Dokumentanzahl und Sentiment-Verteilung
2. bestehende Leistungen mit exaktem Leistungsnamen, zuständiger Stelle, Leistungsart, Ebene, abgedeckten Bedarfen und Prozessrisiken

Klassifiziere jedes Topic in GENAU EINE Kategorie:

1. echte_luecke
Keine bestehende staatliche, kommunale, sozialversicherungsrechtliche oder öffentlich geförderte Leistung deckt den Bedarf substanziell ab.

2. prozessproblem
Mindestens eine bestehende Leistung deckt den Bedarf grundsätzlich ab, aber das Topic deutet auf Probleme beim Zugang oder Ablauf hin:
lange Bearbeitungszeit, komplexe Nachweise, unklare Zuständigkeit, Fristen, Bürokratie, fehlerhafte Bescheide, Auszahlung, Kommunikation mit Behörde.

3. informationsluecke
Mindestens eine bestehende Leistung deckt den Bedarf grundsätzlich ab, aber Bürger scheinen sie nicht zu kennen, nicht zu verstehen oder finden keine verständlichen Informationen dazu.

4. bereits_abgedeckt
Eine bestehende Leistung deckt den Bedarf klar ab und es gibt kein relevantes negatives Signal für Prozess- oder Informationsprobleme.

5. irrelevant
Das Topic passt nicht zu familienbezogenen Sozialleistungen oder ist Noise, z.B. Sprachcluster, Behördenfooter, allgemeine Politik, technische Inhalte.

ENTSCHEIDUNGSREGELN:

- Vergib echte_luecke nur, wenn nach Prüfung der bestehenden Leistungen wirklich keine substanzielle Abdeckung erkennbar ist.
- Wenn eine Leistung existiert, aber das Topic negativ ist, ist meist prozessproblem, nicht echte_luecke.
- Wenn eine Leistung existiert, aber das Topic nach Erklärung, Verständnis, Vergleich oder Orientierung klingt, ist meist informationsluecke.
- Wenn eine Leistung nur grob passt, aber der konkrete Bedarf nicht vollständig gedeckt ist, klassifiziere nicht automatisch echte_luecke. Prüfe zuerst informationsluecke oder prozessproblem.
- Allgemeine Beratungs- und Unterstützungsangebote zählen als Abdeckung für allgemeine Beratungsbedarfe.
- Schwangerschaftsberatung, Stillberatung, Trageberatung und Familienberatung zählen als Abdeckung für Schwangerschafts-/Baby-/Elternunterstützung, sofern sie in der Leistungsliste stehen.
- Familienpatenschaften, Familienberatungsdienste, psychosoziale Beratung, Elternberatung, Schulpsychologische Beratung und Familienunterstützung zählen als Abdeckung für allgemeine familiäre Unterstützungs-, Erziehungs- und psychosoziale Bedarfe, sofern sie in der Leistungsliste stehen.
- Elterngeld, ElterngeldPlus, Elternzeit, Mutterschutz, Mutterschaftsgeld und Kinderkrankengeld zählen als Abdeckung für Geburt, Erwerbstätigkeit, Elternzeitplanung und Einkommensausfall nach Geburt, sofern sie in der Leistungsliste stehen.
- Kindergeld, Kinderzuschlag, Familiengeld, Krippengeld, Wohngeld, Bürgergeld, Sozialhilfe und Bildung und Teilhabe zählen als Abdeckung für finanzielle Belastungen von Familien, sofern sie in der Leistungsliste stehen.
- Private Angebote, reine Kontaktkanäle, Terminreservierungen, Kontaktformulare und reine technische Verfahrensleistungen zählen NICHT als vollwertige Bedarfsabdeckung.
- Reine Rechtsmittel wie Widerspruch oder Klage zählen nicht als eigentliche Sozialleistung, können aber Prozessproblem-Indikatoren sein.

HARTER MATCHING-SERVICE-ZWANG:

- matching_services dürfen AUSSCHLIESSLICH exakte Leistungsnamen enthalten, die in der Liste BESTEHENDE LEISTUNGEN als "LEISTUNGSNAME" vorkommen.
- Verwende NIEMALS zuständige Stellen, Behörden, Träger oder allgemeine Begriffe als matching_services.
- Ungültige matching_services sind z.B.: Familienkasse, Gesundheitsamt, Krankenkasse, Jobcenter, Sozialamt, Jugendamt, Finanzamt, Arbeitgeber, Sozialgericht, Beratungsstelle.
- Erfinde keine Servicenamen.
- Kürze Servicenamen nicht ab.
- Wenn kein exakter Leistungsname aus der Liste passt, setze matching_services auf [].
- Wenn matching_services leer ist, aber der Bedarf thematisch im Scope liegt, prüfe echte_luecke oder irrelevant besonders sorgfältig.

PRIORITÄT:

- 5 = sehr dringlich: stark negatives Topic, hoher Handlungsbedarf, echte_luecke oder massives Prozessproblem
- 4 = dringlich: klares negatives Topic mit bestehender Leistung und deutlichem Prozessproblem
- 3 = mittlere Priorität: Informationslücke oder moderates Prozessproblem
- 2 = niedrig: bereits weitgehend abgedeckt, nur kleine Optimierung
- 1 = sehr niedrig: geringe Relevanz
- 0 = irrelevant oder vollständig bereits_abgedeckt ohne Innovationsbedarf

Weitere Hinweise:
- Nutze negatives Sentiment stärker als Dokumentanzahl.
- Die Anzahl Dokumente ist nur ein schwaches Signal, weil sie durch initiale Keywords verzerrt sein kann.
- Wenn Sentimentdaten fehlen, entscheide anhand Kernproblem, Bedarfen und Prozessrisiken.
- Begründe konkret anhand des Topics und der genannten Leistungen. Keine generischen Standardbegründungen.

=== RELEVANTE TOPICS ===
{topics_block}

=== BESTEHENDE LEISTUNGEN ===
{services_block}

=== AUFGABE ===
Gib für jedes Topic eine strukturierte Klassifizierung aus.

Antworte NUR mit validem JSON in diesem Format:
{{
  "gaps": [
    {{
      "topic_id": "0",
      "kernproblem": "Zusammenfassung des Topic-Problems",
      "klassifizierung": "echte_luecke|prozessproblem|informationsluecke|bereits_abgedeckt|irrelevant",
      "matching_services": ["Exakter LEISTUNGSNAME aus BESTEHENDE LEISTUNGEN"],
      "begruendung": "Konkrete Begründung in 2-3 Sätzen. Erkläre, warum es keine echte Lücke ist, wenn passende Leistungen existieren.",
      "prioritaet": 1,
      "confidence": 0.8,
      "empfehlung_innovation": "Konkreter Auftrag für den Innovation Agent in 1 Satz. Bei bereits_abgedeckt/irrelevant leer."
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=MAX_TOKENS,
    )
    return parse_json_response(response.choices[0].message.content)


def run() -> None:
    print("Gap Analysis Agent gestartet...")
    print(f"Backend: Groq ({MODEL})")

    analysis = load_json(ANALYSIS_PATH)
    reference = load_json(REFERENCE_PATH)

    relevant_topics = analysis.get("llm_interpretation", {}).get("relevant_topics", [])
    services = reference.get("services", [])
    expected_topic_ids = {str(rt.get("topic_id")) for rt in relevant_topics}

    print(f"  {len(relevant_topics)} relevante Topics aus Analysis Agent")
    print(f"  {len(services)} bestehende Leistungen aus Referenz")

    if not relevant_topics:
        print("  Keine relevanten Topics — Abbruch")
        return

    if not services:
        print("  Keine Referenzleistungen — Abbruch")
        return

    print("\nGap Analysis läuft (1 Groq-Call für alle Topics)...")
    raw_result = run_gap_analysis(analysis, reference)
    result = validate_and_normalize_gaps(raw_result, reference, expected_topic_ids)

    gaps = result.get("gaps", [])
    print(f"  {len(gaps)} Topics klassifiziert")

    if len(gaps) != len(relevant_topics):
        print(
            f"  WARNUNG: Erwartet {len(relevant_topics)} Topics, "
            f"erhalten {len(gaps)} Klassifikationen"
        )

    counts = {
        "echte_luecke": 0,
        "prozessproblem": 0,
        "informationsluecke": 0,
        "bereits_abgedeckt": 0,
        "irrelevant": 0,
    }
    review_count = 0
    invalid_matches_removed = 0

    for g in gaps:
        cls = g.get("klassifizierung")
        if cls in counts:
            counts[cls] += 1
        if g.get("needs_review"):
            review_count += 1
        invalid_matches_removed += len(g.get("removed_invalid_matching_services", []))

    print(f"  Echte Lücken: {counts['echte_luecke']}")
    print(f"  Prozessprobleme: {counts['prozessproblem']}")
    print(f"  Informationslücken: {counts['informationsluecke']}")
    print(f"  Bereits abgedeckt: {counts['bereits_abgedeckt']}")
    print(f"  Irrelevant: {counts['irrelevant']}")
    print(f"  Review-Fälle: {review_count}")
    print(f"  Entfernte ungültige Matching Services: {invalid_matches_removed}")

    output = {
        "schema_version": "1.1-de",
        "erstellt_am": now_iso(),
        "modell": MODEL,
        "max_tokens": MAX_TOKENS,
        "zusammenfassung": counts,
        "review_count": review_count,
        "invalid_matches_removed": invalid_matches_removed,
        "gaps": gaps,
    }

    save_json(OUTPUT_PATH, output)
    print(f"\nOutput gespeichert → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
