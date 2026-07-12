"""
Gap Analysis Agent v2: Identifiziert echte Bedarfslücken aus den relevanten Topics
des Analysis Agents durch Abgleich mit der Referenz bestehender Leistungen.

Zwei-Pass-Architektur:
- Pass 1 (1 Call für alle Topics): Klassifikation, customer_journey_phase, cluster_id,
  matching_services, begruendung, prioritaet, confidence. KEINE Empfehlung.
- Pass 2 (1 Call pro relevantem Cluster): genau EINE konkrete empfehlung_innovation,
  die alle Topics des Clusters adressiert. Läuft nur für Cluster, deren Topics in
  {echte_luecke, prozessproblem, informationsluecke} liegen.

Begründung: Der frühere 1-Call-Ansatz überlastete das LLM (Klassifikation + Cluster +
Phase + Empfehlung gleichzeitig) und produzierte Boilerplate-Empfehlungen. Pass 2 zwingt
zu Konkretheit, weil eine Cluster-Empfehlung mehrere Topic-Facetten gleichzeitig adressieren
muss — pauschale Formulierungen funktionieren dort strukturell nicht mehr.

Input:
- data/analysis/analysis_output.json (Analysis Agent Output)
- data/reference/existing_services.json (Referenz bestehender Leistungen v2-de)

Output:
- data/gap_analysis/gap_analysis_output_v2.json (schema 1.2-de)
  Die alte Datei gap_analysis_output.json bleibt unverändert erhalten.

Backend: konfigurierbar via GAP_BACKEND=groq|openai.

Wichtige Robustheitsmaßnahmen:
- Topic-IDs werden konsistent als Strings behandelt.
- Matching Services werden nach Pass 1 gegen echte Referenznamen validiert.
- Erfundenes Matching wie "Familienkasse", "Gesundheitsamt", "Krankenkasse" wird entfernt.
- cluster_id wird deterministisch aus dem dominanten matching_service gebildet
  (consolidate_clusters); die LLM-cluster_id bleibt als cluster_id_llm zur Diagnose erhalten.
- customer_journey_phase wird gegen ein kontrolliertes Vokabular validiert.
- empfehlung_innovation wird nach Pass 2 auf generische Boilerplate geprüft.
"""

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

from agents.human_feedback import (
    gap_reclassifications,
    report_stale_decisions,
    topic_removal_actions,
    topic_removals,
)

load_dotenv()

ANALYSIS_PATH = Path("data/analysis/analysis_output.json")
REFERENCE_PATH = Path("data/reference/existing_services.json")
OUTPUT_PATH = Path("data/gap_analysis/gap_analysis_output.json")          # alt, bleibt unangetastet
OUTPUT_PATH_V2 = Path("data/gap_analysis/gap_analysis_output_v2.json")    # neu

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
BACKEND = os.getenv("GAP_BACKEND", "groq").strip().lower()
MODEL = (
    os.getenv("OPENAI_GAP_MODEL", DEFAULT_OPENAI_MODEL)
    if BACKEND == "openai"
    else os.getenv("GROQ_GAP_MODEL", DEFAULT_GROQ_MODEL)
)
MAX_TOKENS = 6000          # Pass 1 (alle Topics)
MAX_TOKENS_PASS2 = 2500    # Pass 2 (eine Empfehlung pro Cluster, Puffer gegen Truncation)
SCHEMA_VERSION = "1.2-de"

VALID_CLASSIFICATIONS = {
    "echte_luecke",
    "prozessproblem",
    "informationsluecke",
    "bereits_abgedeckt",
    "irrelevant",
}

# Klassen, die eine Innovationsempfehlung erwarten (steuern Pass 2 + Empfehlungsprüfung).
INNOVATION_CLASSES = {"echte_luecke", "prozessproblem", "informationsluecke"}

# Review-Gründe, die eine deterministische Cluster-Bündelung verhindern. Verdachtsfälle
# (Scope-Zweifel / fehlendes valides Matching / echte_luecke trotz Matching) bleiben solo,
# damit z.B. ein fälschlich auf Familiengeld gematchtes Migrations-Topic nicht eingemischt wird.
BLOCKING_CLUSTER_REASONS = {
    "moeglicherweise_ausserhalb_familienleistungs_scope",
    "klassifizierung_setzt_leistung_voraus_aber_keine_valide_leistung_gematcht",
    "echte_luecke_trotz_valider_matching_services",
}

# Kontrolliertes Vokabular für die Customer-Journey-Phase.
ALLOWED_PHASES = {
    "information_suche",
    "antragstellung",
    "bearbeitung",
    "bescheid_und_kommunikation",
    "auszahlung",
    "widerspruch_und_klage",
    "uebergreifend",
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

# Generische Phrasen, die auf Boilerplate-Empfehlungen hindeuten (lowercase Substrings).
GENERIC_PHRASES = [
    "einfach und transparent",
    "transparenten antragsprozess",
    "transparenter antragsprozess",
    "bearbeitungszeit reduzieren",
    "bearbeitungszeit zu reduzieren",
    "zufriedenheit erhöhen",
    "zufriedenheit der familien zu erhöhen",
    "informationen zu verbessern",
    "informationsportal",
]

# Konkrete Marker (Kanal/System/Integration/Stakeholder) als Spezifik-Signal (lowercase).
SPECIFIC_MARKERS = {
    "online",
    "app",
    "portal",
    "chatbot",
    "assistent",
    "hotline",
    "telefon",
    "vor ort",
    "bayernid",
    "elster",
    "elsterformular",
    "bundid",
    "schnittstelle",
    "datenabgleich",
    "vorausgefüllt",
    "automatisch",
    "verknüpfung",
    "integration",
    "elterngeldstelle",
    "sachbearbeiter",
    "väter",
    "alleinerziehende",
}

# Stoplist für die Substantiv-Zählung: generische Nomen UND reine Leistungsnamen zählen
# NICHT als Spezifik. Wenn die einzige "Konkretheit" ein Servicename ist, bleibt es Boilerplate.
GENERIC_NOUNS = {
    "familien",
    "antragsprozess",
    "antragsprozesses",
    "bearbeitungszeit",
    "zufriedenheit",
    "entwicklung",
    "informationen",
    "informationsportal",
    "leistung",
    "leistungen",
    "elterngeld",
    "kindergeld",
    "familiengeld",
    "kinderzuschlag",
    "mutterschaftsgeld",
    "kinderkrankengeld",
    "kinderstartgeld",
    "elterngeldplus",
    "arbeitslosengeld",
    "buergergeld",
    "bürgergeld",
    "sozialhilfe",
}

SPECIFICITY_THRESHOLD = 3

UMLAUT_MAP = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_llm_client():
    if BACKEND == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("OPENAI_API_KEY fehlt in .env")
            return None
        try:
            from openai import OpenAI  # noqa: WPS433
        except ImportError:
            print("openai Paket fehlt. Bitte `pip install -r requirements.txt` ausführen.")
            return None
        return OpenAI(api_key=api_key)

    if BACKEND != "groq":
        print("GAP_BACKEND muss 'groq' oder 'openai' sein")
        return None
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print(
            "GROQ_API_KEY fehlt. Bitte lege eine .env-Datei an "
            "(siehe .env.example) und setze GROQ_API_KEY, bevor du den "
            "Gap Analysis Agent startest."
        )
        return None
    return Groq(api_key=api_key)


def call_llm(client: Any, prompt: str, max_tokens: int, temperature: float) -> dict:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_json_response(response.choices[0].message.content)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def replace_umlauts(text: str) -> str:
    return text.translate(UMLAUT_MAP)


def build_topics_block(analysis: dict) -> str:
    """
    Baut den Topics-Block für Pass 1 — nur relevante Topics mit
    Kernproblem und Sentiment-Verteilung.
    """
    interpretation = analysis.get("llm_interpretation", {})
    removed_topics = topic_removals()
    relevant_topics = [
        rt for rt in interpretation.get("relevant_topics", [])
        if str(rt.get("topic_id")) not in removed_topics
    ]
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
    Kompakte Übersicht aller bestehenden Leistungen für den Pass-1-Kontext.
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


def build_services_block_for_names(reference: dict, names: set[str]) -> str:
    """
    Reichere Service-Beschreibung für Pass 2 — nur die Leistungen, die im Cluster
    via matching_services berührt werden. Liefert mehr Kontext (Beschreibung,
    Antragskanäle) als build_services_block, weil Pass 2 konkret werden muss.
    """
    services = reference.get("services", [])
    block = ""
    for s in services:
        if s.get("name", "") not in names:
            continue
        block += f"\n- LEISTUNGSNAME: {s.get('name', '')}\n"
        block += f"  Beschreibung: {s.get('beschreibung', '')}\n"
        block += f"  Zuständige Stelle: {s.get('zustaendige_stelle', '')}\n"
        block += f"  Antragskanäle: {s.get('antragskanaele', [])}\n"
        block += f"  Prozessrisiken: {s.get('bekannte_prozessrisiken', [])}\n"
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


def normalize_cluster_id(raw: Any, topic_id: str) -> str:
    """
    Normalisiert die vom LLM gelieferte cluster_id auf snake_case.
    Leer/None -> solo_<topic_id>.
    """
    s = replace_umlauts(str(raw or "").strip().lower())
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or f"solo_{topic_id}"


def detect_generic_recommendation(text: str) -> bool:
    """
    Lightweight Generic-Detection ohne externe Dependency.
    Generisch = enthält eine Boilerplate-Phrase UND zu wenig konkrete Spezifik.
    Spezifik = Treffer in SPECIFIC_MARKERS + Anzahl kapitalisierter Substantive
    (Proxy für Nomen), die NICHT in GENERIC_NOUNS stehen (Leistungsnamen zählen nicht).
    """
    if not text:
        return False
    low = text.lower()
    if not any(phrase in low for phrase in GENERIC_PHRASES):
        return False
    marker_hits = sum(1 for marker in SPECIFIC_MARKERS if marker in low)
    cap_nouns = {
        word
        for word in re.findall(r"[A-Za-zÄÖÜäöüß-]+", text)
        if word[:1].isupper() and len(word) > 3 and word.lower() not in GENERIC_NOUNS
    }
    specificity = marker_hits + len(cap_nouns)
    return specificity < SPECIFICITY_THRESHOLD


def build_cluster_summary(gaps: list[dict]) -> dict:
    """Mapping cluster_id -> [topic_ids] plus Anzahl Cluster."""
    mapping: dict[str, list[str]] = defaultdict(list)
    for gap in gaps:
        mapping[gap["cluster_id"]].append(gap["topic_id"])
    return {"anzahl_cluster": len(mapping), "mapping": dict(mapping)}


def consolidate_clusters(gaps: list[dict]) -> None:
    """
    Deterministische Cluster-Bildung statt unzuverlässigem LLM-Clustering.

    Setzt die maßgebliche cluster_id pro Gap. Zwei oder mehr Gaps bilden NUR dann
    einen gemeinsamen Cluster, wenn sie ALLE drei Bedingungen erfüllen:
      - denselben primären matching_service (erster Eintrag) haben,
      - dieselbe klassifizierung haben,
      - und KEINER der beteiligten Gaps einen blockierenden review_reason trägt
        (BLOCKING_CLUSTER_REASONS).
    Alles andere wird solo_<topic_id>. So bleiben Verdachtsfälle (z.B. ein Migrations-
    Topic, das fälschlich auf Familiengeld gematcht wurde) sauber isoliert.

    Die LLM-cluster_id liegt bereits als cluster_id_llm vor (Diagnose) und wird hier
    NICHT verwendet.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for gap in gaps:
        if gap.get("force_solo_cluster"):
            continue
        reasons = {r for r in str(gap.get("review_reason", "")).split(";") if r}
        matches = gap.get("matching_services", [])
        primary = matches[0] if matches else ""
        eligible = bool(primary) and not (reasons & BLOCKING_CLUSTER_REASONS)
        if eligible:
            key = (normalize_cluster_id(primary, gap["topic_id"]), str(gap.get("klassifizierung", "")))
            groups[key].append(gap)

    # Service-Namen, die in mehreren klassifizierungs-Gruppen je >=2 Mitglieder haben,
    # brauchen eine Disambiguierung im cluster_id (sonst Namenskollision).
    service_group_counts: Counter = Counter()
    for (service, _kls), members in groups.items():
        if len(members) >= 2:
            service_group_counts[service] += 1

    assigned = set()
    for (service, kls), members in groups.items():
        if len(members) < 2:
            continue
        cluster_id = service if service_group_counts[service] == 1 else f"{service}_{kls}"
        for gap in members:
            gap["cluster_id"] = cluster_id
            assigned.add(id(gap))

    # Alle nicht gebündelten Gaps werden solo.
    for gap in gaps:
        if id(gap) not in assigned:
            gap["cluster_id"] = f"solo_{gap['topic_id']}"


def validate_and_normalize_gaps(result: dict, reference: dict, expected_topic_ids: set[str]) -> dict:
    """
    Validiert und normalisiert die Pass-1-Gaps.

    Unverändert gegenüber v1: matching_services-Validierung gegen echte Referenznamen,
    Entfernung von Träger-/Behördenbegriffen, Klassifizierungs-Fallback und die bisherigen
    needs_review-Gründe.

    Neu in v2:
    - customer_journey_phase-Validierung (leer / ungültig getrennt geflaggt).
    - Die LLM-cluster_id wird nach cluster_id_llm degradiert (nur Diagnose); die
      maßgebliche cluster_id setzt consolidate_clusters() deterministisch danach.
    - empfehlung_innovation wird hier NICHT geprüft (Pass 2 läuft danach).
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
        problem_text = str(gap.get("kernproblem", "")).lower()
        if "aufenthalt" in problem_text or "migrationshintergrund" in problem_text:
            needs_review_reasons.append("moeglicherweise_ausserhalb_familienleistungs_scope")

        # customer_journey_phase validieren (leer vs. ungültig getrennt).
        phase = str(gap.get("customer_journey_phase", "")).strip()
        if not phase:
            gap["customer_journey_phase_original"] = phase
            gap["customer_journey_phase"] = "uebergreifend"
            needs_review_reasons.append("fehlende_customer_journey_phase")
        elif phase not in ALLOWED_PHASES:
            gap["customer_journey_phase_original"] = phase
            gap["customer_journey_phase"] = "uebergreifend"
            needs_review_reasons.append("ungueltige_customer_journey_phase")
        else:
            gap["customer_journey_phase"] = phase

        # LLM-cluster_id nur zur Diagnose behalten; consolidate_clusters() ist maßgeblich.
        gap["cluster_id_llm"] = normalize_cluster_id(gap.get("cluster_id"), gap["topic_id"])

        if needs_review_reasons:
            gap["needs_review"] = True
            gap["review_reason"] = ";".join(needs_review_reasons)
        else:
            gap["needs_review"] = False
            gap["review_reason"] = ""

        # Fallbacks für optionale Felder.
        gap.setdefault("prioritaet", 0)
        gap.setdefault("confidence", 0.0)
        gap.setdefault("empfehlung_innovation", "")   # wird in Pass 2 befüllt
        gap.setdefault("begruendung", "")
        gap.setdefault("kernproblem", "")

        normalized_gaps.append(gap)

    result["gaps"] = normalized_gaps
    return result


def apply_recommendation_quality_check(gaps: list[dict]) -> None:
    """
    Läuft NACH Pass 2. Prüft empfehlung_innovation der Innovationsklassen auf
    fehlende oder generische Empfehlungen und ergänzt needs_review/review_reason.
    Bereits-abgedeckt/irrelevant bleiben unberührt (leere Empfehlung ist dort korrekt).
    """
    for gap in gaps:
        if gap.get("klassifizierung") not in INNOVATION_CLASSES:
            continue

        empf = str(gap.get("empfehlung_innovation", "")).strip()
        new_reasons = []
        if not empf:
            new_reasons.append("fehlende_empfehlung")
        elif detect_generic_recommendation(empf):
            new_reasons.append("generische_empfehlung")

        if new_reasons:
            existing = [r for r in str(gap.get("review_reason", "")).split(";") if r]
            gap["review_reason"] = ";".join(existing + new_reasons)
            gap["needs_review"] = True


def feedback_questions_matching(action: dict) -> bool:
    """Heuristic: Evaluator feedback says the service matching itself is implausible."""
    text = " ".join([
        str(action.get("recommendation", "")),
        str(action.get("reason", "")),
        str(action.get("human_note", "")),
    ]).lower()
    return any(marker in text for marker in (
        "matching",
        "matching-dienste",
        "passen nicht",
        "passt nicht",
        "nicht passend",
        "semantisch nicht",
        "fraglich",
        "unplausibel",
    ))


def apply_gap_feedback(gaps: list[dict], reclassifications: dict[str, dict]) -> int:
    """Apply accepted/auto reclassify feedback and prevent bad matches from driving clusters."""
    applied = 0
    for gap in gaps:
        action = reclassifications.get(str(gap.get("topic_id", "")))
        if not action:
            continue
        proposed = str(action.get("proposed_value", "")).strip()
        if proposed not in VALID_CLASSIFICATIONS:
            continue

        original = gap.get("klassifizierung")
        gap["original_value"] = action.get("original_value", original)
        if original != proposed:
            gap["klassifizierung_original"] = original
            gap["klassifizierung"] = proposed

        gap["human_override"] = action.get("decision") == "accepted"
        gap["auto_applied_by_evaluator"] = action.get("autonomy") == "auto_apply"
        gap["evaluator_run_id"] = action.get("evaluator_run_id", "")
        gap["evaluator_action_id"] = action.get("action_id", "")
        gap["application_status"] = "applied" if original != proposed else "confirmed_no_change"
        gap["conflict_reason"] = ""
        gap["human_override_reason"] = action.get("recommendation") or action.get("reason", "")

        if feedback_questions_matching(action):
            previous_matches = list(gap.get("matching_services", []))
            if previous_matches:
                gap["matching_services_original"] = previous_matches
                gap["matching_services"] = []
            gap["force_solo_cluster"] = True
            existing = [r for r in str(gap.get("review_reason", "")).split(";") if r]
            if "evaluator_matching_unplausibel" not in existing:
                existing.append("evaluator_matching_unplausibel")
            gap["review_reason"] = ";".join(existing)
            gap["conflict_reason"] = "evaluator_matching_unplausibel"

        applied += 1
    return applied


def run_gap_analysis_pass1(client: Any, analysis: dict, reference: dict) -> dict:
    """
    Pass 1: Ein Groq-Call für alle relevanten Topics. Liefert Klassifikation,
    customer_journey_phase, cluster_id, matching_services, begruendung,
    prioritaet, confidence. KEINE Empfehlung.
    """
    topics_block = build_topics_block(analysis)
    services_block = build_services_block(reference)

    prompt = f"""Du bist der Gap Analysis Agent eines Service Sonar für familienbezogene Sozialleistungen in Bayern.

Deine Aufgabe:
Für JEDES relevante Topic aus dem Analysis Agent entscheidest du, ob das Topic eine echte Bedarfslücke ist
oder ob bestehende Leistungen den Bedarf bereits grundsätzlich abdecken. Zusätzlich ordnest du jedes Topic
einer Customer-Journey-Phase zu und gruppierst Topics mit gemeinsamer Wurzelproblematik zu Clustern.

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

CLUSTER-ERKENNUNG:

Mehrere Topics gehören oft zur selben Wurzelproblematik (z.B. mehrere Elterngeld-Facetten:
Antrag, Höhe, Bescheid, Auszahlung). Erkenne diese selbst.
- Vergib pro Gap eine cluster_id, die die gemeinsame Wurzelproblematik beschreibt.
- cluster_id MUSS snake_case und beschreibend sein,
  z.B. "elterngeld", "bayerisches_familiengeld", "familienberatung".
- Topics mit derselben Wurzelproblematik bekommen DIESELBE cluster_id.
- Die cluster_id beschreibt die LEISTUNG bzw. die Wurzelproblematik, NICHT die Facette oder Phase.
- Verschiedene Facetten DERSELBEN Leistung (Antrag, Höhe, Bescheid, Auszahlung, Väter,
  Migranten, Elternzeit) gehören in DENSELBEN Cluster. Die Facette drückst du über
  customer_journey_phase aus — NICHT über die cluster_id.
- Bilde BEWUSST WENIGE, GROBE Cluster. Orientiere die cluster_id an der dominanten
  Leistung in matching_services.
- Beispiel: Alle Topics rund um Elterngeld (Antrag, Höhe, Bescheid, Väter, Migranten,
  Elternzeit) bekommen DIESELBE cluster_id "elterngeld" — NICHT "elterngeld_fuer_vaeter"
  oder "elterngeld_hoehe".
- Steht ein Topic wirklich allein (keine andere Leistung/Wurzel teilt es), vergib
  cluster_id="solo_<topic_id>", z.B. "solo_4".

CUSTOMER-JOURNEY-PHASE:

Ordne jedem Gap GENAU EINE Phase aus diesem kontrollierten Vokabular zu (customer_journey_phase):
- "information_suche"            Bürger sucht/versteht Informationen, bevor er handelt
- "antragstellung"              Probleme beim Stellen des Antrags (Formulare, Nachweise, Fristen)
- "bearbeitung"                 Probleme während der behördlichen Bearbeitung (Dauer, Zuständigkeit)
- "bescheid_und_kommunikation"  Bescheid unverständlich, Berechnung unklar, Behördenkommunikation
- "auszahlung"                  Probleme bei oder Verzug der Auszahlung
- "widerspruch_und_klage"       Ablehnung, Widerspruch, Rechtsmittel
- "uebergreifend"               betrifft mehrere Phasen / nicht eindeutig zuordenbar
Formuliere das kernproblem so, dass die gewählte Phase erkennbar ist.

=== RELEVANTE TOPICS ===
{topics_block}

=== BESTEHENDE LEISTUNGEN ===
{services_block}

=== AUFGABE ===
Gib für jedes Topic eine strukturierte Klassifizierung aus.
WICHTIG: In diesem Schritt gibst du KEINE Innovationsempfehlung aus — die folgt in einem separaten Schritt.

Antworte NUR mit validem JSON in diesem Format:
{{
  "gaps": [
    {{
      "topic_id": "0",
      "kernproblem": "Zusammenfassung des Topic-Problems, so formuliert dass die Customer-Journey-Phase erkennbar ist",
      "customer_journey_phase": "antragstellung",
      "cluster_id": "elterngeld_antrag_und_bearbeitung",
      "klassifizierung": "echte_luecke|prozessproblem|informationsluecke|bereits_abgedeckt|irrelevant",
      "matching_services": ["Exakter LEISTUNGSNAME aus BESTEHENDE LEISTUNGEN"],
      "begruendung": "Konkrete Begründung in 2-3 Sätzen. Erkläre, warum es keine echte Lücke ist, wenn passende Leistungen existieren.",
      "prioritaet": 1,
      "confidence": 0.8
    }}
  ]
}}
"""

    return call_llm(client, prompt, MAX_TOKENS, temperature=0.2)


def run_gap_analysis_pass2(
    client: Any,
    cluster_id: str,
    gaps_in_cluster: list[dict],
    reference: dict,
) -> str:
    """
    Pass 2: Ein Groq-Call für EINEN Cluster. Liefert genau eine konkrete
    empfehlung_innovation, die alle Topics des Clusters adressiert.
    """
    service_names: set[str] = set()
    for gap in gaps_in_cluster:
        for name in gap.get("matching_services", []):
            service_names.add(name)
    services_block = build_services_block_for_names(reference, service_names)

    topics_block = ""
    for gap in gaps_in_cluster:
        topics_block += f"\n--- Topic {gap.get('topic_id')} ---\n"
        topics_block += f"Kernproblem: {gap.get('kernproblem', '')}\n"
        topics_block += f"Customer-Journey-Phase: {gap.get('customer_journey_phase', '')}\n"
        topics_block += f"Klassifizierung: {gap.get('klassifizierung', '')}\n"
        topics_block += f"Priorität: {gap.get('prioritaet', 0)}\n"
        topics_block += f"Matching Services: {gap.get('matching_services', [])}\n"

    prompt = f"""Du bist der Innovations-Vorbereiter des Service Sonar für familienbezogene Sozialleistungen in Bayern.

Du bekommst EINEN Cluster verwandter Bedarfslücken (mehrere Topics zur selben Wurzelproblematik)
sowie die bestehenden Leistungen, die diese Topics berühren.

Deine Aufgabe:
Formuliere GENAU EINE konkrete Innovationsempfehlung, die ALLE Topics dieses Clusters gemeinsam adressiert.
Die Empfehlung ist ein konkreter Arbeitsauftrag für den Innovation Agent — KEIN Allgemeinplatz.

NICHT SO (verboten, das ist Boilerplate):
- "Entwicklung eines einfachen und transparenten Antragsprozesses für X"
- "... um die Bearbeitungszeit zu reduzieren und die Zufriedenheit zu erhöhen"
- "Entwicklung eines Informationsportals für X"

Deine Empfehlung MUSS konkret benennen:
1. WAS konkret anders wird (die spezifische Intervention, nicht nur "vereinfachen")
2. WELCHE Customer-Journey-Phase(n) adressiert werden
3. WELCHE Stakeholder betroffen sind (z.B. Väter, Alleinerziehende, Elterngeldstelle, Sachbearbeiter)
4. WELCHER Kanal genutzt wird (z.B. Online-Assistent, App, Vor-Ort-Beratung, Hotline, Chatbot)
5. WELCHE Integration mit bestehenden Systemen/Leistungen nötig ist
   (z.B. BayernID, ELSTER, Datenabgleich mit Elterngeldstelle, Verknüpfung mit Bayerischem Familiengeld)

Da die Empfehlung mehrere Topic-Facetten gleichzeitig abdecken muss, reicht eine pauschale
Formulierung strukturell nicht aus.

Positivbeispiel:
"Vorausgefüllter digitaler Elterngeld-Antrag (Phase Antragstellung), der über BayernID die Daten
der Elterngeldstelle automatisch zieht, damit Väter Partnermonate ohne Mehrfacheingaben planen können."

=== CLUSTER: {cluster_id} ===
{topics_block}

=== BESTEHENDE LEISTUNGEN IM CLUSTER-KONTEXT ===
{services_block}

=== AUFGABE ===
Antworte NUR mit validem JSON in diesem Format:
{{
  "empfehlung_innovation": "Eine konkrete Empfehlung in 1-3 Sätzen, die alle Topics des Clusters adressiert."
}}
"""

    parsed = call_llm(client, prompt, MAX_TOKENS_PASS2, temperature=0.3)
    return str(parsed.get("empfehlung_innovation", "")).strip()


def run() -> int:
    print("Gap Analysis Agent v2 gestartet (2-Pass)...")
    print(f"Backend: {BACKEND} ({MODEL})")
    client = get_llm_client()
    if client is None:
        return 1

    analysis = load_json(ANALYSIS_PATH)
    reference = load_json(REFERENCE_PATH)

    report_stale_decisions()
    removal_actions = topic_removal_actions()
    removed_topics = {str(action.get("topic_id") or action.get("target")) for action in removal_actions}
    if removed_topics:
        print(f"  {len(removed_topics)} Topic-Removal Feedback-Aktion(en) aktiv: {sorted(removed_topics)}")

    relevant_topics = [
        rt for rt in analysis.get("llm_interpretation", {}).get("relevant_topics", [])
        if str(rt.get("topic_id")) not in removed_topics
    ]
    services = reference.get("services", [])
    expected_topic_ids = {str(rt.get("topic_id")) for rt in relevant_topics}

    print(f"  {len(relevant_topics)} relevante Topics aus Analysis Agent")
    print(f"  {len(services)} bestehende Leistungen aus Referenz")

    if not relevant_topics:
        print("  Keine relevanten Topics — Abbruch")
        return 0

    if not services:
        print("  Keine Referenzleistungen — Abbruch")
        return 0

    # Pass 1: Strukturierung.
    print("\nPass 1: Strukturierung (1 Groq-Call für alle Topics)...")
    raw_result = run_gap_analysis_pass1(client, analysis, reference)
    result = validate_and_normalize_gaps(raw_result, reference, expected_topic_ids)
    gaps = result.get("gaps", [])

    reclassifications = gap_reclassifications()
    if reclassifications:
        applied = apply_gap_feedback(gaps, reclassifications)
        print(f"  {applied} Gap-Reklassifikation(en) aus Feedback angewendet")

    print(f"  {len(gaps)} Topics klassifiziert")

    if len(gaps) != len(relevant_topics):
        print(
            f"  WARNUNG: Erwartet {len(relevant_topics)} Topics, "
            f"erhalten {len(gaps)} Klassifikationen"
        )

    # Deterministische Cluster-Bildung (ersetzt das LLM-Clustering) + Mapping.
    consolidate_clusters(gaps)
    cluster_summary = build_cluster_summary(gaps)
    clusters: dict[str, list[dict]] = defaultdict(list)
    for g in gaps:
        clusters[g["cluster_id"]].append(g)
    print(f"  {cluster_summary['anzahl_cluster']} Cluster gebildet")

    # Pass 2: Konkretisierung pro relevantem Cluster.
    print("\nPass 2: Konkretisierung (1 Groq-Call pro relevantem Cluster)...")
    pass2_calls = 0
    pass2_skipped = 0
    for cluster_id, cluster_gaps in clusters.items():
        innovation_gaps = [g for g in cluster_gaps if g.get("klassifizierung") in INNOVATION_CLASSES]
        if not innovation_gaps:
            pass2_skipped += 1
            continue
        empfehlung = run_gap_analysis_pass2(client, cluster_id, innovation_gaps, reference)
        pass2_calls += 1
        for g in innovation_gaps:
            g["empfehlung_innovation"] = empfehlung
        print(f"  Cluster '{cluster_id}': Empfehlung generiert ({len(innovation_gaps)} Topics)")

    # Empfehlungs-Qualitätsprüfung NACH Pass 2.
    apply_recommendation_quality_check(gaps)

    # Statistiken (nach Quality-Check, da needs_review sich ändern kann).
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

    print(f"\n  Echte Lücken: {counts['echte_luecke']}")
    print(f"  Prozessprobleme: {counts['prozessproblem']}")
    print(f"  Informationslücken: {counts['informationsluecke']}")
    print(f"  Bereits abgedeckt: {counts['bereits_abgedeckt']}")
    print(f"  Irrelevant: {counts['irrelevant']}")
    print(f"  Review-Fälle: {review_count}")
    print(f"  Entfernte ungültige Matching Services: {invalid_matches_removed}")
    print(f"  Pass-2-Calls: {pass2_calls} (übersprungene Cluster: {pass2_skipped})")

    pass_statistik = {
        "pass1_calls": 1,
        "pass2_calls": pass2_calls,
        "pass2_clusters_skipped": pass2_skipped,
    }

    output = {
        "schema_version": SCHEMA_VERSION,
        "erstellt_am": now_iso(),
        "modell": MODEL,
        "max_tokens": MAX_TOKENS,
        "max_tokens_pass2": MAX_TOKENS_PASS2,
        "zusammenfassung": counts,
        "cluster_zusammenfassung": cluster_summary,
        "pass_statistik": pass_statistik,
        "review_count": review_count,
        "invalid_matches_removed": invalid_matches_removed,
        "feedback_audit": {
            "topic_removals": [
                {
                    "topic_id": str(action.get("topic_id") or action.get("target")),
                    "evaluator_run_id": action.get("evaluator_run_id", ""),
                    "evaluator_action_id": action.get("action_id", ""),
                    "original_value": action.get("original_value"),
                    "auto_applied_by_evaluator": action.get("autonomy") == "auto_apply",
                    "human_override": action.get("decision") == "accepted",
                    "application_status": "applied_topic_excluded",
                    "conflict_reason": "",
                }
                for action in removal_actions
            ]
        },
        "gaps": gaps,
    }

    save_json(OUTPUT_PATH_V2, output)
    print(f"\nOutput gespeichert → {OUTPUT_PATH_V2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
