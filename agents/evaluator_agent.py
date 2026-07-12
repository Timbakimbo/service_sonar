"""
Evaluator Agent: Bewertet alle Vorgänger-Agent-Outputs (Analysis, Gap v2, Innovation),
prüft Cross-Pass-Konsistenz, gibt Keyword-/System-Feedback und produziert Aktions-Listen.
Schließt den Reasoning-Kreislauf des MAS.

4-Pass-Kaskade (abhängig):
  Pass 1 — Topic-Evaluation (alle 28 Topics)
  Pass 2 — Gap-Evaluation (nur in_scope-Topics; Rest deterministisch skipped)
  Pass 3 — Innovation-Evaluation (mit Cross-Pass-Kontext)
  Pass 4 — Aggregation + System-Feedback

Output: data/evaluation/evaluator_output.json (schema_version "1.0-de").
Backend: konfigurierbar via EVALUATOR_BACKEND=groq|openai.

Determinismus-Split: evaluation_ids, aggregierte_aktionen (mit normalisierten Konvergenz-Labels),
rework_warteschlange, Cross-Pass-Override (Gap remove/reclassify ⇒ Innovation rework),
skipped-Verdicts, reclassify-Vokabular-Check und source_stats_status setzt der Code.
Plausibilität, Begründungen, Briefings, Konvergenz, Keyword-Feedback liefert das LLM.

Robustheit: per-Pass try/except, Markdown-Fence-Stripping, response_format json_object.
"""

import json
import os
import re
import hashlib
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

ANALYSIS_PATH = Path("data/analysis/analysis_output.json")
GAP_V2_PATH = Path("data/gap_analysis/gap_analysis_output_v2.json")
INNOVATION_PATH = Path("data/innovation/innovation_output.json")
REFERENCE_PATH = Path("data/reference/existing_services.json")
METRICS_PATH = Path("data/metrics.json")
OUTPUT_PATH = Path("data/evaluation/evaluator_output.json")

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
BACKEND = os.getenv("EVALUATOR_BACKEND", "groq").strip().lower()
MODEL = (
    os.getenv("OPENAI_EVALUATOR_MODEL", DEFAULT_OPENAI_MODEL)
    if BACKEND == "openai"
    else os.getenv("GROQ_EVALUATOR_MODEL", DEFAULT_GROQ_MODEL)
)
SCHEMA_VERSION = "1.0-de"
MAX_TOKENS_PASS1 = 4000
MAX_TOKENS_PASS2 = 4000
MAX_TOKENS_PASS3 = 5000
MAX_TOKENS_PASS4 = 6000

VALID_CLASSIFICATIONS = {
    "echte_luecke", "prozessproblem", "informationsluecke", "bereits_abgedeckt", "irrelevant",
}
HIGH_CONFIDENCE_THRESHOLD = 0.85

client: Any | None = None


def get_llm_client() -> Any:
    if BACKEND == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY fehlt in .env")
        try:
            from openai import OpenAI  # noqa: WPS433
        except ImportError as exc:
            raise RuntimeError("openai Paket fehlt. Bitte requirements installieren.") from exc
        return OpenAI(api_key=api_key)

    if BACKEND != "groq":
        raise RuntimeError("EVALUATOR_BACKEND muss 'groq' oder 'openai' sein")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY fehlt in .env")
    return Groq(api_key=api_key)


# --------------------------------------------------------------------------- helpers
def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_evaluator_run_id() -> str:
    return f"ER_{datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:10]}"


def stable_action_id(action_type: str, stable_target: str) -> str:
    digest = hashlib.sha256(f"{action_type}|{stable_target}".encode("utf-8")).hexdigest()[:16]
    return f"EA_{action_type}_{digest}"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_json_response(content: str) -> dict:
    content = content.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(content)


def dedupe(items: list) -> list:
    seen: set = set()
    out: list = []
    for it in items:
        if it not in seen:
            out.append(it)
            seen.add(it)
    return out


def truncate(text: str, n: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def normalize_konvergenz_label(label: Any) -> str:
    """Run-stabile Kanonisierung: lowercase, non-alphanum->_, Tokens alphabetisch sortiert."""
    s = re.sub(r"[^a-z0-9]+", "_", str(label or "").lower()).strip("_")
    tokens = sorted(t for t in s.split("_") if t)
    return "_".join(tokens)


def load_keywords() -> list[str]:
    try:
        from config.keywords import KEYWORDS  # noqa: WPS433
        return list(KEYWORDS)
    except Exception:
        ns: dict = {}
        path = Path("config/keywords.py")
        if path.exists():
            exec(path.read_text(encoding="utf-8"), ns)  # noqa: S102 (Thesis-Config)
            return list(ns.get("KEYWORDS", []))
        return []


def call_llm(prompt: str, max_tokens: int, temperature: float = 0.2) -> dict:
    global client
    if client is None:
        client = get_llm_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return parse_json_response(response.choices[0].message.content)


# --------------------------------------------------------------------------- inputs
def build_source_stats(metrics_path: Path) -> tuple[dict, str]:
    """Defensiv: missing / list-of-runs (partial) / per-source-dict (complete)."""
    if not metrics_path.exists():
        return {}, "missing"
    data = load_json(metrics_path)
    if isinstance(data, list):
        if not data:
            return {}, "missing"
        # save_metrics haengt pro Quelle einen eigenen Record an (Feld "source").
        # Legacy-Records (alte Web-Laeufe) haben kein "source" -> als web behandeln.
        # Pro Quelle den jeweils juengsten Record nehmen (Liste ist chronologisch).
        latest_by_source: dict[str, dict] = {}
        for rec in data:
            if not isinstance(rec, dict):
                continue
            src = rec.get("source", "web")
            if src in ("web", "reddit", "fragdenstaat"):
                latest_by_source[src] = rec
        if not latest_by_source:
            return {}, "missing"
        present = [s for s in ("web", "reddit", "fragdenstaat") if s in latest_by_source]
        status = "complete" if len(present) == 3 else "partial"
        return latest_by_source, status
    if isinstance(data, dict):
        present = [k for k in ("web", "reddit", "fragdenstaat") if k in data]
        status = "complete" if len(present) >= 3 else ("partial" if present else "missing")
        return data, status
    return {}, "missing"


def load_evaluator_inputs() -> dict:
    analysis = load_json(ANALYSIS_PATH)
    gap_data = load_json(GAP_V2_PATH)
    innovation_data = load_json(INNOVATION_PATH)
    reference = load_json(REFERENCE_PATH)
    source_stats, source_stats_status = build_source_stats(METRICS_PATH)

    interpretation = analysis.get("llm_interpretation", {})
    relevant_by_id = {str(t.get("topic_id")): t for t in interpretation.get("relevant_topics", [])}
    irrelevant_by_id = {str(t.get("topic_id")): t for t in interpretation.get("irrelevante_topics", [])}
    topic_sentiments = {str(k): v for k, v in analysis.get("topic_sentiments", {}).items()}

    return {
        "analysis": analysis,
        "topic_overview": analysis.get("topic_overview", []),
        "relevant_by_id": relevant_by_id,
        "irrelevant_by_id": irrelevant_by_id,
        "topic_sentiments": topic_sentiments,
        "gaps": gap_data.get("gaps", []),
        "innovations": innovation_data.get("innovations", []),
        "reference": reference,
        "keywords": load_keywords(),
        "source_stats": source_stats,
        "source_stats_status": source_stats_status,
    }


# --------------------------------------------------------------------------- block builders
def build_services_compact(reference: dict) -> str:
    block = ""
    for s in reference.get("services", []):
        block += f"\n- {s.get('name','')} | Bedarfe: {s.get('abgedeckte_bedarfe', [])}"
        block += f" | Prozessrisiken: {s.get('bekannte_prozessrisiken', [])}"
    return block


def build_topics_block(inputs: dict) -> str:
    block = ""
    for t in inputs["topic_overview"]:
        tid = str(t.get("Topic"))
        if tid in inputs["relevant_by_id"]:
            urteil = f"relevant — {inputs['relevant_by_id'][tid].get('kernproblem', '')}"
        elif tid in inputs["irrelevant_by_id"]:
            urteil = f"irrelevant — {inputs['irrelevant_by_id'][tid].get('grund', '')}"
        else:
            urteil = "unbewertet"
        block += f"\n--- Topic {tid} ---"
        block += f"\nName: {t.get('Name', '')}"
        block += f"\nAnzahl Dokumente: {t.get('Count', 0)}"
        block += f"\nTop-Begriffe: {t.get('Representation', [])[:10]}"
        block += f"\nSentiment: {inputs['topic_sentiments'].get(tid, {})}"
        block += f"\nAnalysis-Urteil: {urteil}"
    return block


# --------------------------------------------------------------------------- passes
def run_pass1_topics(inputs: dict) -> dict:
    prompt = f"""Du bist der Evaluator Agent eines Service Sonar für familienbezogene Sozialleistungen in Bayern.
Du prüfst die Arbeit des Analysis Agent: für JEDES Topic entscheidest du, ob es wirklich in den
Familienleistungs-Kontext gehört, ob es Noise ist, und ob es mit anderen Topics redundant ist.

Bewerte pro Topic:
- in_scope (bool): gehört das Topic thematisch zu familienbezogenen Sozialleistungen in Bayern?
- noise (bool): NUR technisches Crawling-Artefakt OHNE inhaltliche Kohärenz.
- redundancy_cluster (string|null): snake_case-Wurzelthema, das mehrere Topics teilen (z.B. "elterngeld"); null wenn allein.
- verdict: "keep" (relevant, eigenständig) | "remove" (Noise/out-of-scope) | "merge" (redundant).
- unambiguous (bool): ist das Urteil fachlich eindeutig genug für eine begrenzte Auto-Korrektur?
- confidence (0.0-1.0): tatsächliche Sicherheit des Urteils; nicht pauschal setzen.
- begruendung: 1-2 konkrete Sätze; bei remove MUSS klar werden, ob Noise oder out-of-scope.

NOISE vs. OUT-OF-SCOPE — strikt trennen:
- noise=true bedeutet: technisches Crawling-Artefakt OHNE inhaltliche Kohärenz. Beispiele:
  reCAPTCHA/Cookie-Banner, Sprach-/Übersetzungsmüll, Footer-/Navigations-Boilerplate, HTML/CSS-Fragmente.
- in_scope=false OHNE noise=true bedeutet: inhaltlich kohärentes, verständliches Topic, das aber
  thematisch NICHT zu familienbezogenen Sozialleistungen in Bayern gehört. Beispiele:
  Migrationsrecht/Aufenthaltsstatus, Arbeitslosenversicherung (Bundes-Thema), Coronavirus allgemein,
  Verkehrsmittel/Fahrerlaubnis. Diese sind KEIN Noise.
- Beide Fälle bekommen verdict "remove", aber die Begründung muss klar benennen, welcher Fall vorliegt.

Regeln:
- Überstimme den Analysis Agent, wenn nötig (false-positives UND false-negatives).
- Mehrere Elterngeld-Facetten (Antrag, Höhe, Bescheid, Väter) gehören in DENSELBEN redundancy_cluster, verdict "merge".
- noise=true impliziert in_scope=false und verdict "remove".

=== AKTIVE KEYWORDS ===
{inputs['keywords']}
=== QUELLEN-STATISTIK (Status: {inputs['source_stats_status']}) ===
{json.dumps(inputs['source_stats'], ensure_ascii=False)}
=== TOPICS ==={build_topics_block(inputs)}

Antworte NUR mit validem JSON:
{{ "topic_evaluations": [ {{ "topic_id":"14","in_scope":true,"noise":false,
  "unambiguous":true,"confidence":0.9,
  "redundancy_cluster":"elterngeld","verdict":"merge","begruendung":"..." }} ] }}
"""
    return call_llm(prompt, MAX_TOKENS_PASS1, temperature=0.2)


def run_pass2_gaps(inputs: dict, pass1: dict) -> dict:
    in_scope = {str(e.get("topic_id")) for e in pass1.get("topic_evaluations", []) if e.get("in_scope")}
    # Pass-1-Failure -> konservativ alle Gaps bewerten lassen (siehe Risiko 7).
    if not pass1.get("topic_evaluations"):
        in_scope = {str(g.get("topic_id")) for g in inputs["gaps"]}

    scope_block = ""
    for e in pass1.get("topic_evaluations", []):
        scope_block += f"\n- Topic {e.get('topic_id')}: in_scope={e.get('in_scope')} verdict={e.get('verdict')}"

    gaps_block = ""
    for g in inputs["gaps"]:
        if str(g.get("topic_id")) not in in_scope:
            continue
        gaps_block += f"\n--- Gap Topic {g.get('topic_id')} ---"
        gaps_block += f"\nKernproblem: {g.get('kernproblem', '')}"
        gaps_block += f"\nKlassifizierung: {g.get('klassifizierung', '')}"
        gaps_block += f"\nMatching Services: {g.get('matching_services', [])}"
        gaps_block += f"\nEmpfehlung: {truncate(g.get('empfehlung_innovation', ''), 300)}"

    prompt = f"""Du bist der Evaluator Agent. Du prüfst die Klassifizierungen des Gap Analysis Agent gegen die
bestehenden Leistungen und gegen die Topic-Bewertung aus dem vorherigen Schritt.
Bewerte NUR die unten aufgeführten Gaps (alle in_scope).

Bewerte pro Gap:
- klassifikation_plausibel (bool): passt die Klassifizierung zum kernproblem?
- matching_plausibel (bool): passen die matching_services semantisch? (z.B. ein reines Gesundheits-Topic
  auf "Kinderkrankengeld" zu mappen ist fragwürdig.)
- empfehlung_qualitaet: "gut" | "vage" | "boilerplate".
- verdict: "accept" | "reclassify" | "remove".
- vorgeschlagene_klassifikation: nur bei reclassify, aus {sorted(VALID_CLASSIFICATIONS)}.
- unambiguous (bool): ist die Reklassifikation fachlich eindeutig?
- confidence (0.0-1.0): tatsächliche Sicherheit; nicht pauschal setzen.
- begruendung: 1-2 Sätze.

=== TOPIC-BEWERTUNGEN ==={scope_block}
=== BESTEHENDE LEISTUNGEN ==={build_services_compact(inputs['reference'])}
=== ZU BEWERTENDE GAPS ==={gaps_block}

Antworte NUR mit validem JSON:
{{ "gap_evaluations": [ {{ "topic_id":"10","klassifikation_plausibel":false,
  "matching_plausibel":false,"empfehlung_qualitaet":"vage","verdict":"reclassify",
  "vorgeschlagene_klassifikation":"informationsluecke","unambiguous":true,
  "confidence":0.9,"begruendung":"..." }} ] }}
"""
    return call_llm(prompt, MAX_TOKENS_PASS2, temperature=0.2)


def run_pass3_innovations(inputs: dict, pass1: dict, pass2: dict) -> dict:
    verdicts_block = ""
    for e in pass2.get("gap_evaluations", []):
        verdicts_block += f"\n- Gap Topic {e.get('topic_id')}: verdict={e.get('verdict')}"
        if e.get("vorgeschlagene_klassifikation"):
            verdicts_block += f" (vorschlag: {e.get('vorgeschlagene_klassifikation')})"

    innovations_block = ""
    for i in inputs["innovations"]:
        innovations_block += f"\n--- {i.get('innovation_id')} ---"
        innovations_block += f"\nTitel: {i.get('titel', '')}"
        innovations_block += f"\nTyp: {i.get('innovation_typ', '')} | Klassifizierung: {i.get('klassifizierung', '')}"
        innovations_block += f"\nAdressierte Topics: {i.get('addressierte_topics', [])}"
        innovations_block += f"\nLösung: {truncate(i.get('konkrete_loesung', ''), 320)}"
        innovations_block += f"\nTräger: {i.get('moegliche_traeger', [])}"
        innovations_block += f"\nIntegrationspunkte: {i.get('integrationspunkte', [])}"

    prompt = f"""Du bist der Evaluator Agent. Du prüfst die Innovationen auf Domain-Plausibilität und Konsistenz
mit der Gap-Bewertung aus dem vorherigen Schritt. Wenn der zugrundeliegende Gap als fragwürdig
(reclassify/remove) bewertet wurde, ist die Innovation als rework zu markieren mit Begründung "gap_basis_fraglich".

Bewerte pro Innovation:
- domain_plausibilitaet (bool): passt die Lösung inhaltlich zur Domäne?
- traeger_domain_plausibel (bool): ist der vorgeschlagene Träger für die Domäne ZUSTÄNDIG?
  Unplausibel z.B.: "Kultusministerium" für Gesundheit/Pflege; "Krankenkasse" für Schul-Themen;
  "Familienkasse" für Pflege. Wenn false -> verdict MUSS rework oder merge_with_other sein, nicht accept.
- integrationspunkte_plausibel (bool): passen die Integrationspunkte (BayernID/ELSTER etc.) zur Lösung?
  Strikte Regeln:
  * BayernID nur sinnvoll, wo Identifikation echten Mehrwert bringt (Antragsabwicklung, persönliche
    Bescheid-Einsicht). NICHT bei anonymer Beratung/Foren (widerspricht Anonymität), NICHT bei
    niedrigschwelliger Beratung (Stillberatung, Trageberatung — keine Authentifizierung nötig),
    NICHT für öffentlich zugängliche Informationen.
  * ELSTER nur sinnvoll, wo Einkommens-/Steuerdaten relevant sind (Elterngeld, Familiengeld,
    Kinderzuschlag). NICHT für Foren, Beratungs- oder Informations-Services ohne Geldleistung.
- traeger_in_integrationspunkten (bool): wurde fälschlich ein Träger als Integrationspunkt deklariert?
- konvergenz_cluster (string|null): identifiziert das LÖSUNGSMUSTER, NICHT die Domäne oder den Titel.
  Zwei Innovationen gehören in denselben konvergenz_cluster, wenn ihre konkrete Lösung strukturell
  gleich ist, auch wenn sie unterschiedliche Leistungen adressieren. Beispiele:
  * "Digitaler Assistent mit BayernID + ELSTER für Antragstellung" ist DASSELBE Pattern, egal ob für
    Elterngeld, Familiengeld oder Kindergeld -> "digitaler_antragsassistent_bayernid_elster".
  * "Interaktiver Online-Planer mit Visualisierung" ist DASSELBE Pattern, egal welche Leistung
    -> "interaktiver_planer".
  * Nur wenn die Lösung strukturell anders ist (Forum vs. Beratungs-Tool vs. Antragsassistent), anderer Cluster.
  FALSCH im letzten Lauf: INN_001=digitaler_assistent_bayernid, INN_004=elterngeld_assistent,
  INN_008=familiengeld_navigator als drei verschiedene Cluster — obwohl alle drei strukturell
  "digitaler Assistent + BayernID + ELSTER + Datenabgleich" sind. RICHTIG: EIN gemeinsamer Cluster
  "digitaler_antragsassistent_bayernid_elster".
- verdict: "accept" | "rework" | "merge_with_other". accept NUR, wenn domain_plausibilitaet,
  traeger_domain_plausibel und integrationspunkte_plausibel alle true sind.
- rework_briefing: nur bei rework — konkrete Anweisung, was anders gemacht werden soll.
- begruendung: 1-2 Sätze.

=== GAP-VERDICTS (Kontext) ==={verdicts_block}
=== ZU BEWERTENDE INNOVATIONEN ==={innovations_block}

Antworte NUR mit validem JSON:
{{ "innovation_evaluations": [ {{ "innovation_id":"INN_006","domain_plausibilitaet":true,
  "traeger_domain_plausibel":false,"integrationspunkte_plausibel":false,
  "traeger_in_integrationspunkten":false,
  "konvergenz_cluster":"digitaler_antragsassistent_bayernid_elster","verdict":"rework",
  "rework_briefing":"...","begruendung":"..." }} ] }}
"""
    return call_llm(prompt, MAX_TOKENS_PASS3, temperature=0.2)


def run_pass4_aggregation(inputs: dict, pass1: dict, pass2: dict, pass3: dict) -> dict:
    topics_summary = ""
    for e in pass1.get("topic_evaluations", []):
        topics_summary += f"\n- T{e.get('topic_id')}: {e.get('verdict')} — {truncate(e.get('begruendung', ''), 100)}"

    gap_klass = {str(g.get("topic_id")): g.get("klassifizierung", "") for g in inputs["gaps"]}
    gaps_summary = ""
    for e in pass2.get("gap_evaluations", []):
        tid = str(e.get("topic_id"))
        gaps_summary += f"\n- T{tid}: orig={gap_klass.get(tid, '')} verdict={e.get('verdict')}"
        if e.get("vorgeschlagene_klassifikation"):
            gaps_summary += f" -> {e.get('vorgeschlagene_klassifikation')}"

    p3_by_id = {e.get("innovation_id"): e for e in pass3.get("innovation_evaluations", [])}
    innovations_summary = ""
    for i in inputs["innovations"]:
        iid = i.get("innovation_id")
        ev = p3_by_id.get(iid, {})
        innovations_summary += (
            f"\n- {iid} '{i.get('titel', '')}': verdict={ev.get('verdict', 'n/a')}"
            f" topics={i.get('addressierte_topics', [])}"
            f" konvergenz={normalize_konvergenz_label(ev.get('konvergenz_cluster'))}"
        )

    services = inputs["reference"].get("services", [])
    bedarfe = sorted({b for s in services for b in s.get("abgedeckte_bedarfe", [])})
    themes_block = f"Abgedeckte Bedarfe: {bedarfe}\nLeistungen: {[s.get('name', '') for s in services]}"

    prompt = f"""Du bist der Evaluator Agent. Du fasst die Gesamtbewertung zusammen und gibst System-Feedback
für den nächsten Pipeline-Durchlauf.

Aufgaben:
1. priorisierung: ranke NUR die als "accept" markierten Innovationen (Rang 1..N) mit Begründung.
   rework-Innovationen NICHT ranken.
2. konvergenz_status: ist das Themenspektrum vollständig? Welche typischen Familienthemen fehlen
   (z.B. Pflege, Sorgerecht/Umgangsrecht, Kita-Zuschuss, Fördermittel, Unterhalt)?
3. keyword_feedback:
   - schwache_keywords: aktive Keywords, die v.a. Noise lieferten (thematisch, KEINE Quantifizierung —
     1:1 Keyword-zu-Topic-Tracking existiert nicht).
   - neue_keywords_vorgeschlagen: für die identifizierten Themen-Lücken.

=== QUELLEN-STATISTIK (Status: {inputs['source_stats_status']}) ===
{json.dumps(inputs['source_stats'], ensure_ascii=False)}
=== AKTIVE KEYWORDS ===
{inputs['keywords']}
=== TOPIC-VERDICTS ==={topics_summary}
=== GAP-VERDICTS ==={gaps_summary}
=== INNOVATION-VERDICTS ==={innovations_summary}
=== THEMENSPEKTRUM BESTEHENDER LEISTUNGEN ===
{themes_block}

Antworte NUR mit validem JSON:
{{ "priorisierung":[{{"rang":1,"innovation_id":"INN_004","begruendung":"..."}}],
  "konvergenz_status":{{"themenspektrum_vollstaendig":false,"fehlende_themen":["pflege","sorgerecht"]}},
  "keyword_feedback":{{"schwache_keywords":["..."],"neue_keywords_vorgeschlagen":["..."]}} }}
"""
    return call_llm(prompt, MAX_TOKENS_PASS4, temperature=0.4)


# --------------------------------------------------------------------------- deterministic aggregation
def build_aggregierte_aktionen(pass1_evals: list, pass2_evals: list, pass3_evals: list) -> dict:
    regenerieren = [e["innovation_id"] for e in pass3_evals if e.get("verdict") == "rework"]
    reklassifizieren = [e["topic_id"] for e in pass2_evals if e.get("verdict") == "reclassify"]
    topics_entfernen = [e["topic_id"] for e in pass1_evals if e.get("verdict") == "remove"]
    konvergenz: dict[str, list] = defaultdict(list)
    for e in pass3_evals:
        label = normalize_konvergenz_label(e.get("konvergenz_cluster"))
        if label:
            konvergenz[label].append(e["innovation_id"])
    zusammenfuehren = [dedupe(ids) for ids in konvergenz.values() if len(dedupe(ids)) >= 2]
    return {
        "regenerieren": dedupe(regenerieren),
        "reklassifizieren": dedupe(reklassifizieren),
        "topics_entfernen": dedupe(topics_entfernen),
        "konvergenz_zusammenfuehren": zusammenfuehren,
    }


def confidence_value(evaluation: dict) -> float | None:
    try:
        value = float(evaluation.get("confidence"))
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, value))


def classify_topic_remove_autonomy(evaluation: dict) -> tuple[str, float | None, str]:
    confidence = confidence_value(evaluation)
    if evaluation.get("noise") is True:
        return "auto_apply", confidence, "low"
    auto_safe = (
        evaluation.get("verdict") == "remove"
        and evaluation.get("in_scope") is False
        and evaluation.get("unambiguous") is True
        and confidence is not None
        and confidence >= HIGH_CONFIDENCE_THRESHOLD
    )
    if auto_safe:
        return "auto_apply", confidence, "low"
    return "human_required", confidence, "medium"


def build_source_quality_warnings(source_stats: dict) -> list[dict]:
    warnings: list[dict] = []
    reddit = source_stats.get("reddit", {}) if isinstance(source_stats, dict) else {}
    attempted = int(reddit.get("attempted_requests") or 0)
    blocked = int(reddit.get("blocked_403_count") or 0)
    successful = int(reddit.get("successful_requests") or 0)
    if attempted and (successful == 0 or blocked / attempted >= 0.8):
        warnings.append({
            "source": "reddit",
            "status": "blocked_or_stale",
            "attempted_requests": attempted,
            "blocked_403_count": blocked,
            "successful_requests": successful,
            "existing_data_preserved": bool(reddit.get("existing_data_preserved")),
            "reason": "Letzter Reddit-Run lieferte keine frischen Daten und wurde überwiegend/komplett mit 403 blockiert.",
        })
    return warnings


def build_actions(output: dict, inputs: dict) -> list[dict]:
    actions: list[dict] = []
    evaluator_run_id = str(output.get("evaluator_run_id", "unbound"))
    gaps_by_topic = {str(g.get("topic_id")): g for g in inputs.get("gaps", [])}
    innovations_by_id = {
        str(item.get("innovation_id")): item for item in inputs.get("innovations", [])
    }

    def add(action: dict) -> None:
        stable_target = str(action["stable_target"])
        action["evaluator_run_id"] = evaluator_run_id
        action["action_id"] = stable_action_id(action["action_type"], stable_target)
        actions.append(action)

    for topic in output.get("topic_evaluations", []):
        if topic.get("verdict") != "remove":
            continue
        autonomy, confidence, risk = classify_topic_remove_autonomy(topic)
        topic_id = str(topic.get("topic_id", ""))
        add({
            "action_type": "topic_remove", "target_agent": "gap-analysis",
            "target": topic_id, "topic_id": topic_id, "stable_target": f"topic:{topic_id}",
            "autonomy": autonomy, "confidence": confidence, "risk": risk,
            "original_value": "in_scope",
            "recommendation": topic.get("begruendung", "Topic entfernen"),
            "reason": topic.get("begruendung", ""),
        })

    for gap in output.get("gap_evaluations", []):
        if gap.get("verdict") != "reclassify":
            continue
        topic_id = str(gap.get("topic_id", ""))
        original_gap = gaps_by_topic.get(topic_id, {})
        cluster_id = str(original_gap.get("cluster_id") or f"solo_{topic_id}")
        proposed = gap.get("vorgeschlagene_klassifikation")
        confidence = confidence_value(gap)
        auto_safe = (
            proposed in VALID_CLASSIFICATIONS and proposed != "echte_luecke"
            and gap.get("unambiguous") is True
            and confidence is not None and confidence >= HIGH_CONFIDENCE_THRESHOLD
        )
        add({
            "action_type": "gap_reclassify", "target_agent": "gap-analysis",
            "target": topic_id, "topic_id": topic_id, "cluster_id": cluster_id,
            "stable_target": f"gap:{cluster_id}:topic:{topic_id}",
            "proposed_value": proposed,
            "autonomy": "auto_apply" if auto_safe else "human_required",
            "confidence": confidence, "risk": "low" if auto_safe else "high",
            "original_value": original_gap.get("klassifizierung"),
            "recommendation": gap.get("begruendung", "Gap reklassifizieren"),
            "reason": gap.get("begruendung", ""),
        })

    gap_evaluations = {str(item.get("topic_id")): item for item in output.get("gap_evaluations", [])}
    for topic_id, original_gap in gaps_by_topic.items():
        if original_gap.get("klassifizierung") != "echte_luecke":
            continue
        cluster_id = str(original_gap.get("cluster_id") or f"solo_{topic_id}")
        evaluation = gap_evaluations.get(topic_id, {})
        reason = evaluation.get("begruendung") or original_gap.get("begruendung") or (
            "Neue Behauptung einer echten Luecke muss fachlich geprueft werden."
        )
        add({
            "action_type": "real_gap_review", "target_agent": "gap-analysis",
            "target": cluster_id, "topic_id": topic_id, "cluster_id": cluster_id,
            "stable_target": f"gap:{cluster_id}:topic:{topic_id}",
            "autonomy": "human_required", "confidence": confidence_value(evaluation), "risk": "high",
            "original_value": "echte_luecke", "recommendation": reason, "reason": reason,
            "evaluator_verdict": evaluation.get("verdict", "not_evaluated"),
        })

    by_id = {item.get("innovation_id"): item for item in output.get("innovation_evaluations", [])}
    for innovation_id in output.get("aggregierte_aktionen", {}).get("regenerieren", []):
        evaluation = by_id.get(innovation_id, {})
        innovation = innovations_by_id.get(str(innovation_id), {})
        cluster_id = str(innovation.get("cluster_id") or "missing_cluster")
        add({
            "action_type": "innovation_rework", "target_agent": "innovation",
            "target": cluster_id, "cluster_id": cluster_id, "display_target": innovation_id,
            "innovation_id": innovation_id, "stable_target": f"cluster:{cluster_id}",
            "autonomy": "human_required", "confidence": confidence_value(evaluation), "risk": "medium",
            "original_value": innovation.get("titel", ""),
            "recommendation": evaluation.get("rework_briefing") or evaluation.get("begruendung", ""),
            "reason": evaluation.get("begruendung", ""),
        })

    for innovation_ids in output.get("aggregierte_aktionen", {}).get("konvergenz_zusammenfuehren", []):
        cluster_ids = sorted({
            str(innovations_by_id.get(str(iid), {}).get("cluster_id", ""))
            for iid in innovation_ids if innovations_by_id.get(str(iid), {}).get("cluster_id")
        })
        if len(cluster_ids) < 2:
            continue
        stable_target = "clusters:" + "|".join(cluster_ids)
        add({
            "action_type": "innovation_merge", "target_agent": "innovation",
            "target": stable_target, "stable_target": stable_target, "targets": cluster_ids,
            "display_targets": innovation_ids, "autonomy": "human_required",
            "confidence": None, "risk": "medium", "original_value": cluster_ids,
            "recommendation": "Konvergente Innovationen fachlich zusammenführen",
            "reason": "Mehrere Innovationen folgen demselben Lösungsmuster.",
        })

    feedback = output.get("keyword_feedback", {})
    for action_type, field, label in (
        ("keyword_add", "neue_keywords_vorgeschlagen", "Keyword hinzufügen"),
        ("keyword_remove", "schwache_keywords", "Schwaches Keyword entfernen"),
    ):
        for keyword in feedback.get(field, []) or []:
            add({
                "action_type": action_type, "target_agent": "source-discovery/reddit-scraper",
                "target": keyword, "stable_target": f"keyword:{str(keyword).casefold()}",
                "autonomy": "human_required", "confidence": None, "risk": "medium",
                "original_value": None, "recommendation": f"{label}: {keyword}",
                "reason": "Keyword-Aenderungen veraendern die Datengrundlage und brauchen Freigabe.",
            })

    for warning in build_source_quality_warnings(inputs.get("source_stats", {})):
        add({
            "action_type": "source_quality_warning", "target_agent": "source-discovery/reddit-scraper",
            "target": warning["source"], "stable_target": f"source:{warning['source']}",
            "autonomy": "suggestion_only", "confidence": 1.0, "risk": "engineering",
            "original_value": warning.get("status"), "recommendation": warning["reason"],
            "reason": warning["reason"], "details": warning,
        })

    return actions


def build_rework_warteschlange(pass3_evals: list) -> list:
    return [
        {"innovation_id": e["innovation_id"], "issue": truncate(e.get("rework_briefing", ""), 160)}
        for e in pass3_evals
        if e.get("verdict") == "rework"
    ]


def ensure_priorisierung_vollstaendig(priorisierung: list, accept_ids: set) -> list:
    """
    Garantiert, dass jede accept-Innovation in der priorisierung steht.
    1. Behalte nur LLM-Ränge für tatsächlich accept-markierte Innovationen.
    2. Hänge fehlende accept-IDs deterministisch ans Ende (rang = max+i),
       markiert mit deterministisch_angehaengt=true, sodass LLM- vs. Code-Einträge
       unterscheidbar bleiben.
    """
    ranked = []
    present = set()
    for item in priorisierung:
        innovation_id = item.get("innovation_id")
        if innovation_id not in accept_ids or innovation_id in present:
            continue
        ranked.append(dict(item))
        present.add(innovation_id)

    for iid in sorted(accept_ids - present):
        ranked.append({
            "rang": 0,
            "innovation_id": iid,
            "begruendung": "vom LLM nicht explizit geranked, deterministisch ans Ende angehängt",
            "deterministisch_angehaengt": True,
        })
    for rank, item in enumerate(ranked, start=1):
        item["rang"] = rank
    return ranked


# --------------------------------------------------------------------------- validation
def validate_evaluator_output(out: dict, inputs: dict, pass_failures: list) -> dict:
    reasons: list[str] = []
    gaps_v2 = inputs["gaps"]
    innovations = inputs["innovations"]

    # Pass-2: gap_evaluations deterministisch neu aufbauen (1 Eintrag pro gap-v2-Gap).
    if out["topic_evaluations"]:
        in_scope = {str(e.get("topic_id")) for e in out["topic_evaluations"] if e.get("in_scope")}
    else:
        in_scope = {str(g.get("topic_id")) for g in gaps_v2}  # Fallback: nicht alles skippen
    llm_by_topic = {str(e.get("topic_id")): e for e in out["gap_evaluations"]}
    rebuilt = []
    for g in gaps_v2:
        tid = str(g.get("topic_id"))
        if tid not in in_scope:
            rebuilt.append({"topic_id": tid, "verdict": "skipped_due_to_topic_out_of_scope",
                            "begruendung": "Topic in Pass 1 als out-of-scope/remove bewertet."})
            continue
        ge = dict(llm_by_topic.get(tid, {
            "topic_id": tid, "verdict": "accept",
            "begruendung": "keine LLM-Bewertung erhalten", "needs_review": True,
        }))
        ge["topic_id"] = tid
        if ge.get("verdict") == "reclassify" and ge.get("vorgeschlagene_klassifikation") not in VALID_CLASSIFICATIONS:
            ge["needs_review"] = True
            reasons.append(f"ungueltige_reklassifikation:{tid}")
        rebuilt.append(ge)
    out["gap_evaluations"] = rebuilt

    # Cross-Pass-Konsistenz: Gap remove/reclassify ⇒ Innovation rework (Pass 2 ist Wahrheit).
    bad_topics = {e["topic_id"] for e in out["gap_evaluations"] if e["verdict"] in ("remove", "reclassify")}
    inn_topics = {i.get("innovation_id"): {str(t) for t in i.get("addressierte_topics", [])} for i in innovations}
    for ie in out["innovation_evaluations"]:
        iid = ie.get("innovation_id")
        # (a) Gap-Basis fraglich (Cross-Pass)
        if inn_topics.get(iid, set()) & bad_topics and ie.get("verdict") == "accept":
            ie["verdict"] = "rework"
            ie["begruendung"] = "gap_basis_fraglich (Cross-Pass-Override): " + str(ie.get("begruendung", ""))
            if not str(ie.get("rework_briefing", "")).strip():
                ie["rework_briefing"] = ("Gap-Basis wurde in Pass 2 als fragwürdig bewertet — "
                                         "Klassifikation/Matching zuerst klären.")
        # (b) Träger nicht für Domäne zuständig
        if ie.get("verdict") == "accept" and ie.get("traeger_domain_plausibel") is False:
            ie["verdict"] = "rework"
            ie["begruendung"] = "traeger_domain_inkonsistent (Override): " + str(ie.get("begruendung", ""))
            if not str(ie.get("rework_briefing", "")).strip():
                ie["rework_briefing"] = "Träger ist für die Domäne nicht zuständig — passenden Träger wählen."
        # (c) Integrationspunkte unpassend
        if ie.get("verdict") == "accept" and ie.get("integrationspunkte_plausibel") is False:
            ie["verdict"] = "rework"
            ie["begruendung"] = "integrationspunkte_inkonsistent (Override): " + str(ie.get("begruendung", ""))
            if not str(ie.get("rework_briefing", "")).strip():
                ie["rework_briefing"] = ("Integrationspunkte (z.B. BayernID/ELSTER) passen nicht zur "
                                         "Lösung — entfernen oder passende wählen.")
        # rework ohne Briefing -> review
        if ie.get("verdict") == "rework" and not str(ie.get("rework_briefing", "")).strip():
            ie["needs_review"] = True
            reasons.append(f"rework_ohne_briefing:{iid}")

    # evaluation_id-Vergabe (deterministisch).
    for i, e in enumerate(out["topic_evaluations"], 1):
        e["evaluation_id"] = f"TE_{i:03d}"
    for i, e in enumerate(out["gap_evaluations"], 1):
        e["evaluation_id"] = f"GE_{i:03d}"
    for i, e in enumerate(out["innovation_evaluations"], 1):
        e["evaluation_id"] = f"IE_{i:03d}"

    for p in pass_failures:
        reasons.append(f"pass_failure:{p}")

    out["review_count"] = (
        sum(1 for sec in ("topic_evaluations", "gap_evaluations", "innovation_evaluations")
            for e in out[sec] if e.get("needs_review"))
        + len(pass_failures)
    )
    out["review_reasons"] = reasons
    return out


def sanitize_pass_result(pass_id: str, result: Any, inputs: dict) -> dict:
    """Keep only entries usable by the existing downstream contract."""
    if not isinstance(result, dict):
        raise ValueError("LLM-Antwort ist kein JSON-Objekt")

    if pass_id == "pass1_topics":
        valid_ids = {str(item.get("Topic")) for item in inputs.get("topic_overview", [])}
        usable = [
            item for item in result.get("topic_evaluations", [])
            if isinstance(item, dict)
            and str(item.get("topic_id", "")) in valid_ids
            and item.get("verdict") in {"keep", "remove", "merge"}
            and isinstance(item.get("in_scope"), bool)
            and isinstance(item.get("noise"), bool)
        ] if isinstance(result.get("topic_evaluations"), list) else []
        if not usable:
            raise ValueError("keine brauchbare Topic-Evaluation")
        return {**result, "topic_evaluations": usable}

    if pass_id == "pass2_gaps":
        valid_ids = {str(item.get("topic_id")) for item in inputs.get("gaps", [])}
        usable = []
        candidates = result.get("gap_evaluations", [])
        for item in candidates if isinstance(candidates, list) else []:
            if not isinstance(item, dict) or str(item.get("topic_id", "")) not in valid_ids:
                continue
            verdict = item.get("verdict")
            if verdict not in {"accept", "reclassify", "remove"}:
                continue
            if verdict == "reclassify" and item.get("vorgeschlagene_klassifikation") not in VALID_CLASSIFICATIONS:
                continue
            usable.append(item)
        if not usable:
            raise ValueError("keine brauchbare Gap-Evaluation")
        return {**result, "gap_evaluations": usable}

    if pass_id == "pass3_innovations":
        valid_ids = {str(item.get("innovation_id")) for item in inputs.get("innovations", [])}
        candidates = result.get("innovation_evaluations", [])
        usable = [
            item for item in candidates
            if isinstance(item, dict)
            and str(item.get("innovation_id", "")) in valid_ids
            and item.get("verdict") in {"accept", "rework", "merge_with_other"}
        ] if isinstance(candidates, list) else []
        if not usable:
            raise ValueError("keine brauchbare Innovation-Evaluation")
        return {**result, "innovation_evaluations": usable}

    if pass_id == "pass4_aggregation":
        if not (
            isinstance(result.get("priorisierung"), list)
            and isinstance(result.get("konvergenz_status"), dict)
            and isinstance(result.get("keyword_feedback"), dict)
        ):
            raise ValueError("Aggregation verletzt den bestehenden Output-Vertrag")
        return result

    raise ValueError(f"unbekannter Evaluator-Pass: {pass_id}")


# --------------------------------------------------------------------------- orchestration
def run() -> int:
    global client
    print("Evaluator Agent gestartet (4-Pass)...")
    print(f"Backend: {BACKEND} ({MODEL})")

    try:
        inputs = load_evaluator_inputs()
        client = get_llm_client()
    except Exception as exc:
        print(f"FEHLER: Evaluator-Konfiguration/Initialisierung fehlgeschlagen: {exc}")
        print("Bestehender Evaluator-Output bleibt unverändert.")
        return 1
    print(f"  {len(inputs['topic_overview'])} Topics | {len(inputs['gaps'])} Gaps | "
          f"{len(inputs['innovations'])} Innovationen | source_stats={inputs['source_stats_status']}")

    pass_failures: list[str] = []
    successful_passes: set[str] = set()

    def safe(pass_id, label, fn, fallback):
        try:
            print(f"  {label} ...")
            result = sanitize_pass_result(pass_id, fn(), inputs)
            successful_passes.add(pass_id)
            return result
        except Exception as exc:
            print(f"  FEHLER in {label}: {exc} — Pass übersprungen")
            pass_failures.append(pass_id)
            return fallback

    pass1 = safe("pass1_topics", "Pass 1 (Topics)", lambda: run_pass1_topics(inputs),
                 {"topic_evaluations": []})
    pass2 = safe("pass2_gaps", "Pass 2 (Gaps)", lambda: run_pass2_gaps(inputs, pass1),
                 {"gap_evaluations": []})
    pass3 = safe("pass3_innovations", "Pass 3 (Innovationen)",
                 lambda: run_pass3_innovations(inputs, pass1, pass2),
                 {"innovation_evaluations": []})
    pass4 = safe("pass4_aggregation", "Pass 4 (Aggregation)",
                 lambda: run_pass4_aggregation(inputs, pass1, pass2, pass3),
                 {"priorisierung": [], "konvergenz_status": {}, "keyword_feedback": {}})

    if not successful_passes.intersection({"pass1_topics", "pass2_gaps", "pass3_innovations"}):
        print("FEHLER: Alle inhaltlichen Evaluator-Pässe sind fehlgeschlagen oder unbrauchbar.")
        print("Bestehender Evaluator-Output bleibt unverändert.")
        return 1

    out = {
        "topic_evaluations": pass1.get("topic_evaluations", []),
        "gap_evaluations": pass2.get("gap_evaluations", []),
        "innovation_evaluations": pass3.get("innovation_evaluations", []),
        "priorisierung": pass4.get("priorisierung", []),
        "konvergenz_status": pass4.get("konvergenz_status", {}),
        "keyword_feedback": pass4.get("keyword_feedback", {}),
    }
    out = validate_evaluator_output(out, inputs, pass_failures)

    # priorisierung: nur accept-Innovationen, und garantiert vollständig (Code-Fallback).
    accept_ids = {e["innovation_id"] for e in out["innovation_evaluations"] if e.get("verdict") == "accept"}
    out["priorisierung"] = ensure_priorisierung_vollstaendig(out["priorisierung"], accept_ids)

    aggregierte_aktionen = build_aggregierte_aktionen(
        out["topic_evaluations"], out["gap_evaluations"], out["innovation_evaluations"])
    rework_warteschlange = build_rework_warteschlange(out["innovation_evaluations"])

    skipped = sum(1 for e in out["gap_evaluations"] if e["verdict"] == "skipped_due_to_topic_out_of_scope")
    pass_statistik = {
        "pass1_topics_evaluated": len(out["topic_evaluations"]),
        "pass2_gaps_evaluated": len(out["gap_evaluations"]) - skipped,
        "pass2_gaps_skipped_out_of_scope": skipped,
        "pass3_innovations_evaluated": len(out["innovation_evaluations"]),
        "pass4_aggregation_calls": 0 if "pass4_aggregation" in pass_failures else 1,
    }

    evaluator_run_id = new_evaluator_run_id()
    output = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_run_id": evaluator_run_id,
        "erstellt_am": now_iso(),
        "output_status": "partial" if pass_failures else "complete",
        "failed_pass_count": len(pass_failures),
        "failed_passes": pass_failures,
        "modell_backend": BACKEND,
        "modell": MODEL,
        "pass_statistik": pass_statistik,
        "source_stats_status": inputs["source_stats_status"],
        "topic_evaluations": out["topic_evaluations"],
        "gap_evaluations": out["gap_evaluations"],
        "innovation_evaluations": out["innovation_evaluations"],
        "priorisierung": out["priorisierung"],
        "rework_warteschlange": rework_warteschlange,
        "konvergenz_status": out["konvergenz_status"],
        "keyword_feedback": out["keyword_feedback"],
        "aggregierte_aktionen": aggregierte_aktionen,
        "source_quality_warnings": build_source_quality_warnings(inputs["source_stats"]),
        "review_count": out["review_count"],
        "review_reasons": out["review_reasons"],
    }
    output["aktionen"] = build_actions(output, inputs)

    save_json(OUTPUT_PATH, output)
    print(f"\n  Pass-Failures: {pass_failures or 'keine'} | Review: {out['review_count']}")
    print(f"  Priorisiert (accept): {len(out['priorisierung'])} | Rework: {len(rework_warteschlange)}")
    print(f"Output gespeichert → {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
