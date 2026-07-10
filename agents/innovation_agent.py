"""
Innovation Agent: Erzeugt pro relevantem Cluster GENAU EINE konkrete, umsetzbare
Innovationsidee, die alle Topics des Clusters adressiert.

Input:
- data/gap_analysis/gap_analysis_output_v2.json (Gap Agent v2, cluster-basiert)
- data/reference/existing_services.json (Anknüpfungspunkte + Träger-Ableitung)

Output:
- data/innovation/innovation_output.json (schema_version "1.0-de")

Backend: Groq (Llama 3.3 70B), 1 Call pro relevantem Cluster.

Determinismus-Split: Fakten, die bereits feststehen (cluster_id, addressierte_topics,
betroffene_leistungen, klassifizierung, adressierte_phasen), setzt der Code. Nur was Urteil
erfordert, kommt vom LLM. Reduziert Halluzination und macht den Output reproduzierbar.

Robustheit (gespiegelt vom Gap Agent v2): Markdown-Fence-Stripping, response_format json_object,
Whitelist-/Exakt-Validierung, per-Cluster try/except.
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

from agents.human_feedback import innovation_merge_groups, innovation_rework_briefings

load_dotenv()

GAP_V2_PATH = Path("data/gap_analysis/gap_analysis_output_v2.json")
REFERENCE_PATH = Path("data/reference/existing_services.json")
OUTPUT_PATH = Path("data/innovation/innovation_output.json")

MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 3000
SCHEMA_VERSION = "1.0-de"

VALID_INNOVATION_TYPES = {
    "prozess_optimierung",
    "digitalisierung",
    "informations_service",
    "beratungsangebot",
    "neue_leistung",
    "programm_erweiterung",
}

# Geordnete Tupel: erstes Element ist der Coerce-Default bei Mismatch/ungültigem Typ.
TYP_BY_KLASS = {
    "prozessproblem": ("prozess_optimierung", "digitalisierung"),
    "informationsluecke": ("informations_service", "beratungsangebot"),
    "echte_luecke": ("neue_leistung", "programm_erweiterung"),
}

VALID_AUFWAND = {"klein", "mittel", "gross"}

# Kontrolliertes Phasen-Vokabular (gespiegelt aus dem Gap Agent).
ALLOWED_PHASES = {
    "information_suche",
    "antragstellung",
    "bearbeitung",
    "bescheid_und_kommunikation",
    "auszahlung",
    "widerspruch_und_klage",
    "uebergreifend",
}

SKIP_KLASS = {"bereits_abgedeckt", "irrelevant"}
SKIP_REVIEW_REASON = "moeglicherweise_ausserhalb_familienleistungs_scope"

TITLE_MIN_CHARS = 20   # untere Schranke (Zeichen, passt zu deutschen Komposita-Titeln)
TITLE_MAX_CHARS = 80   # obere Schranke (Zeichen-Cap, fängt Bindestrich-Komposita)

# Kuratierte Whitelist öffentlicher Träger (kanonische Formen). Private/freie Träger und
# Rauschen ("Unklar", Privatbanken) bewusst raus. L-Bank (BW) nicht enthalten (User-Entscheidung).
TRAEGER_WHITELIST = {
    "ZBFS",
    "StMAS",
    "Familienkasse",
    "Jugendamt",
    "Krankenkassen",
    "Sozialamt",
    "Jobcenter",
    "Agentur für Arbeit",
    "Deutsche Rentenversicherung",
    "Elterngeldstelle",
    "Wohngeldstelle",
    "Bezirk Oberbayern",
    "Kommune",
    "Land Bayern",
    "Bund",
    "Bundesministerium für Familie, Senioren, Frauen und Jugend",
    "Bayerisches Staatsministerium für Unterricht und Kultus",
    "Bayerisches Staatsministerium für Ernährung, Landwirtschaft und Forsten",
    "Bundesamt für Justiz",
}

# Alias-Map (lowercase -> kanonische Whitelist-Form). Reconciles Vollnamen <-> Abkürzungen.
TRAEGER_ALIASES = {
    "zentrum bayern familie und soziales": "ZBFS",
    "zbfs": "ZBFS",
    "staatsministerium für arbeit und soziales, familie und integration": "StMAS",
    "bayerisches staatsministerium für arbeit und soziales, familie und integration": "StMAS",
    "stmas": "StMAS",
    "krankenkasse": "Krankenkassen",
    "kommunal": "Kommune",
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


def parse_json_response(content: str) -> dict:
    """Robustes JSON-Parsing — entfernt Markdown-Fences falls vorhanden."""
    content = content.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(content)


def get_valid_service_names(reference: dict) -> set[str]:
    return {
        str(s.get("name", "")).strip()
        for s in reference.get("services", [])
        if str(s.get("name", "")).strip()
    }


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            out.append(it)
            seen.add(it)
    return out


def topic_sort_key(tid: str):
    return (0, int(tid)) if tid.isdigit() else (1, tid)


def clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def canonical_traeger(name: str) -> str | None:
    """Kanonisiert einen Trägernamen über Alias-Map + case-insensitive Whitelist-Abgleich."""
    low = str(name).strip().lower()
    if not low:
        return None
    if low in TRAEGER_ALIASES:
        return TRAEGER_ALIASES[low]
    for w in TRAEGER_WHITELIST:
        if w.lower() == low:
            return w
    return None


def match_service_names(valid_service_names: set[str], items: list) -> tuple[list[str], list[str]]:
    """Exakter (case-insensitiver) Abgleich gegen echte Leistungsnamen. Wie Gap Agent v2."""
    lookup = {n.lower(): n for n in valid_service_names}
    valid: list[str] = []
    removed: list[str] = []
    for it in items or []:
        s = str(it).strip()
        if not s:
            continue
        if s in valid_service_names:
            valid.append(s)
        elif s.lower() in lookup:
            valid.append(lookup[s.lower()])
        else:
            removed.append(s)
    return dedupe(valid), removed


def should_skip_cluster(cluster_gaps: list[dict]) -> tuple[bool, str]:
    klass = {g.get("klassifizierung", "") for g in cluster_gaps}
    if klass & SKIP_KLASS:
        return True, "klassifizierung_bereits_abgedeckt_oder_irrelevant"
    if any(SKIP_REVIEW_REASON in str(g.get("review_reason", "")) for g in cluster_gaps):
        return True, "ausserhalb_familienleistungs_scope"
    return False, ""


def aggregate_cluster(cluster_gaps: list[dict], reference: dict) -> dict:
    services_by_name = {s.get("name", ""): s for s in reference.get("services", [])}

    topics = sorted((str(g.get("topic_id", "")) for g in cluster_gaps), key=topic_sort_key)

    betroffene: list[str] = []
    for g in cluster_gaps:
        for s in g.get("matching_services", []):
            betroffene.append(str(s))
    betroffene = dedupe(betroffene)

    phasen = sorted({
        g.get("customer_journey_phase", "")
        for g in cluster_gaps
        if g.get("customer_journey_phase")
    })

    klass_list = [g.get("klassifizierung", "") for g in cluster_gaps]
    klass = Counter(klass_list).most_common(1)[0][0] if klass_list else ""

    prioritaet_max = max((clamp_int(g.get("prioritaet", 0), 0, 5, 0) for g in cluster_gaps), default=0)

    empfehlungen: list[str] = dedupe([
        str(g.get("empfehlung_innovation", "")).strip()
        for g in cluster_gaps
        if str(g.get("empfehlung_innovation", "")).strip()
    ])

    service_kontext = {
        name: {
            "bedarfe": services_by_name.get(name, {}).get("abgedeckte_bedarfe", []),
            "prozessrisiken": services_by_name.get(name, {}).get("bekannte_prozessrisiken", []),
        }
        for name in betroffene
    }

    return {
        "addressierte_topics": topics,
        "betroffene_leistungen": betroffene,
        "adressierte_phasen": phasen,
        "klassifizierung": klass,
        "prioritaet_max": prioritaet_max,
        "gap_empfehlungen": empfehlungen,
        "service_kontext": service_kontext,
        "topics_detail": [
            {
                "topic_id": str(g.get("topic_id", "")),
                "kernproblem": g.get("kernproblem", ""),
                "phase": g.get("customer_journey_phase", ""),
            }
            for g in cluster_gaps
        ],
    }


def build_innovation_prompt(cluster_id: str, agg: dict) -> str:
    klass = agg["klassifizierung"]
    erlaubte_typen = ", ".join(TYP_BY_KLASS.get(klass, ()))
    traeger_liste = ", ".join(sorted(TRAEGER_WHITELIST))

    topics_block = ""
    for t in agg["topics_detail"]:
        topics_block += f"\n- Topic {t['topic_id']} [Phase: {t['phase']}]: {t['kernproblem']}"

    gap_empf_block = ""
    for e in agg["gap_empfehlungen"]:
        gap_empf_block += f"\n- {e}"

    rework_block = ""
    if agg.get("rework_feedback"):
        feedback = agg["rework_feedback"]
        rework_block = f"""

=== AKZEPTIERTES EVALUATOR-REWORK ===
Diese Innovation wurde im vorherigen Evaluator-Lauf für Rework markiert. Berücksichtige diese
Anweisung explizit und vermeide denselben Fehler:
- {feedback.get('recommendation') or feedback.get('reason') or feedback.get('human_note') or ''}
"""

    services_block = ""
    for name, ctx in agg["service_kontext"].items():
        services_block += f"\n- LEISTUNGSNAME: {name}"
        services_block += f"\n  abgedeckte Bedarfe: {ctx['bedarfe']}"
        services_block += f"\n  bekannte Prozessrisiken: {ctx['prozessrisiken']}"

    return f"""Du bist der Innovation Agent eines Service Sonar für familienbezogene Sozialleistungen in Bayern.

Du bekommst EINEN Cluster verwandter Bedarfslücken (mehrere Topics zur selben Wurzelproblematik)
plus die bestehenden Leistungen, die diese Topics berühren, mit ihren abgedeckten Bedarfen und
bekannten Prozessrisiken.

Deine Aufgabe:
Entwirf GENAU EINE konkrete, umsetzbare Innovation, die ALLE Topics dieses Clusters gemeinsam adressiert.
Die Innovation ist ein konkreter Lösungsvorschlag — KEINE Absichtserklärung.

NICHT SO (verboten, zu vage):
- "Verbesserung der Familiensituation"
- "Optimierung des Antragsprozesses zur Steigerung der Zufriedenheit"
- "Eine App für Familien"

GUT (konkret, mit System-Anknüpfung):
- "Vorausgefüllter digitaler Elterngeld-Antrag, der über BayernID die Einkommensdaten der
  Elterngeldstelle und das ELSTER-System anbindet, sodass Väter und Mütter Partnermonate
  ohne Mehrfacheingaben planen und die Bescheid-Berechnung live nachvollziehen können."

Deine Innovation MUSS konkret benennen:
1. die spezifische Intervention (was genau passiert, welche Schritte sich ändern)
2. konkrete Zielgruppen (z.B. "Väter mit Partnermonats-Antrag", nicht "Familien allgemein")
3. realistische Träger aus der erlaubten Liste
4. Anknüpfungspunkte an bestehende Leistungen (exakte Leistungsnamen)
5. konkrete Integrationspunkte (z.B. BayernID, ELSTER-Schnittstelle, Datenabgleich Elterngeldstelle)
6. konkrete Umsetzungshürden (mindestens eine, keine Floskeln)

KONTROLLIERTE VOKABULARE:
- innovation_typ: für klassifizierung "{klass}" sind NUR erlaubt: {erlaubte_typen}
- geschaetzter_aufwand: klein | mittel | gross
- moegliche_traeger: AUSSCHLIESSLICH aus dieser Liste (Abkürzung oder Vollname): {traeger_liste}
- anknuepfungspunkte: AUSSCHLIESSLICH exakte Leistungsnamen aus BETROFFENE LEISTUNGEN.
- titel: prägnant, 20 bis 80 Zeichen.

=== CLUSTER: {cluster_id} ===
Gemeinsame Klassifizierung: {klass}
Adressierte Customer-Journey-Phasen: {agg['adressierte_phasen']}

Topics in diesem Cluster:{topics_block}

Bisherige Gap-Empfehlungen (als Inspiration, nicht wörtlich übernehmen):{gap_empf_block}
{rework_block}

=== BETROFFENE LEISTUNGEN (Anknüpfungspunkte + Kontext) ==={services_block}

=== AUFGABE ===
Antworte NUR mit validem JSON in diesem Format:
{{
  "innovation_typ": "einer der erlaubten Typen",
  "titel": "prägnant, 20-80 Zeichen",
  "kurzbeschreibung": "1-2 Sätze Elevator Pitch",
  "konkrete_loesung": "3-5 Sätze: was passiert genau, welche Schritte ändern sich",
  "zielgruppen": ["konkrete Zielgruppe"],
  "moegliche_traeger": ["Träger aus der Liste"],
  "anknuepfungspunkte": ["exakter Leistungsname"],
  "integrationspunkte": ["BayernID", "ELSTER-Schnittstelle"],
  "erwarteter_nutzen": "2-3 Sätze für Bürger und Verwaltung",
  "umsetzungshuerden": ["Hürde 1", "Hürde 2"],
  "geschaetzter_aufwand": "klein|mittel|gross",
  "prioritaet": 4,
  "confidence": 0.7
}}
"""


def run_innovation(cluster_id: str, agg: dict) -> dict:
    prompt = build_innovation_prompt(cluster_id, agg)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=MAX_TOKENS,
    )
    return parse_json_response(response.choices[0].message.content)


def validate_innovation(raw: dict, cluster_id: str, agg: dict, valid_service_names: set[str]) -> dict:
    inn = dict(raw)
    reasons: list[str] = []

    # Deterministische Felder mergen (überschreiben etwaige LLM-Werte).
    inn["cluster_id"] = cluster_id
    inn["addressierte_topics"] = agg["addressierte_topics"]
    inn["betroffene_leistungen"] = agg["betroffene_leistungen"]
    inn["klassifizierung"] = agg["klassifizierung"]
    inn["adressierte_phasen"] = agg["adressierte_phasen"]

    # innovation_typ: Vokabular + Passung zur klassifizierung — hart erzwungen via COERCE.
    typ = str(inn.get("innovation_typ", "")).strip()
    erlaubt = TYP_BY_KLASS.get(agg["klassifizierung"], ())
    default_typ = erlaubt[0] if erlaubt else typ
    if typ not in VALID_INNOVATION_TYPES:
        inn["innovation_typ_original"] = typ
        inn["innovation_typ"] = default_typ
        reasons.append("ungueltiger_innovation_typ")
    elif typ not in erlaubt:
        inn["innovation_typ_original"] = typ
        inn["innovation_typ"] = default_typ
        reasons.append("typ_passt_nicht_zu_klassifizierung")
    else:
        inn["innovation_typ"] = typ

    # geschaetzter_aufwand.
    if str(inn.get("geschaetzter_aufwand", "")).strip() not in VALID_AUFWAND:
        reasons.append("ungueltiger_aufwand")

    # moegliche_traeger gegen Whitelist (Alias-Map).
    valid_tr: list[str] = []
    removed_tr: list[str] = []
    for t in inn.get("moegliche_traeger", []) or []:
        c = canonical_traeger(str(t))
        if c:
            valid_tr.append(c)
        else:
            removed_tr.append(str(t))
    inn["moegliche_traeger"] = dedupe(valid_tr)
    if removed_tr:
        inn["removed_invalid_traeger"] = removed_tr
    if not inn["moegliche_traeger"]:
        reasons.append("fehlende_traeger")

    # anknuepfungspunkte: exakte Leistungsnamen.
    valid_ak, removed_ak = match_service_names(valid_service_names, inn.get("anknuepfungspunkte", []))
    inn["anknuepfungspunkte"] = valid_ak
    if removed_ak:
        inn["removed_invalid_anknuepfungspunkte"] = removed_ak
    if not valid_ak and agg["klassifizierung"] != "echte_luecke":
        reasons.append("fehlende_anknuepfungspunkte")

    # umsetzungshuerden: min. 1.
    huerden = [str(h).strip() for h in (inn.get("umsetzungshuerden") or []) if str(h).strip()]
    inn["umsetzungshuerden"] = huerden
    if len(huerden) < 1:
        reasons.append("fehlende_huerden")

    # titel: Zeichen-Unter- und -Obergrenze (Wortzählung passt für dt. Komposita nicht).
    titel = str(inn.get("titel", "")).strip()
    if len(titel) < TITLE_MIN_CHARS:
        reasons.append("titel_zu_kurz")
    if len(titel) > TITLE_MAX_CHARS:
        reasons.append("titel_zu_lang")

    # prioritaet / confidence klemmen.
    inn["prioritaet"] = clamp_int(inn.get("prioritaet", agg["prioritaet_max"]), 0, 5, agg["prioritaet_max"])
    inn["confidence"] = clamp_float(inn.get("confidence", 0.0), 0.0, 1.0, 0.0)

    # Fallbacks für Pflichtfelder.
    for f in ("titel", "kurzbeschreibung", "konkrete_loesung", "erwarteter_nutzen"):
        inn.setdefault(f, "")
    inn.setdefault("zielgruppen", [])
    inn.setdefault("integrationspunkte", [])

    inn["needs_review"] = bool(reasons)
    inn["review_reason"] = ";".join(reasons)
    return inn


def order_innovation(inn: dict) -> dict:
    """Stabile Feldreihenfolge für lesbaren Output."""
    order = [
        "innovation_id", "cluster_id", "addressierte_topics", "betroffene_leistungen",
        "klassifizierung", "innovation_typ", "innovation_typ_original", "titel",
        "kurzbeschreibung", "konkrete_loesung", "adressierte_phasen", "zielgruppen",
        "moegliche_traeger", "removed_invalid_traeger", "anknuepfungspunkte",
        "removed_invalid_anknuepfungspunkte", "integrationspunkte", "erwarteter_nutzen",
        "umsetzungshuerden", "geschaetzter_aufwand", "prioritaet", "confidence",
        "needs_review", "review_reason",
    ]
    ordered = {k: inn[k] for k in order if k in inn}
    for k, v in inn.items():  # etwaige Restfelder anhängen
        ordered.setdefault(k, v)
    return ordered


def run() -> None:
    print("Innovation Agent gestartet...")
    print(f"Backend: Groq ({MODEL})")

    gap_data = load_json(GAP_V2_PATH)
    reference = load_json(REFERENCE_PATH)
    valid_service_names = get_valid_service_names(reference)

    gaps = gap_data.get("gaps", [])
    if not gaps:
        print("  Keine Gaps im v2-Output — Abbruch")
        return

    clusters: dict[str, list[dict]] = defaultdict(list)
    for g in gaps:
        clusters[str(g.get("cluster_id", ""))].append(g)

    print(f"  {len(clusters)} Cluster aus Gap Agent v2")

    innovations: list[dict] = []
    skipped = 0
    inn_counter = 1
    rework_by_innovation_id = innovation_rework_briefings()

    for cluster_id, cluster_gaps in clusters.items():
        skip, reason = should_skip_cluster(cluster_gaps)
        if skip:
            skipped += 1
            print(f"  SKIP '{cluster_id}' ({reason})")
            continue

        agg = aggregate_cluster(cluster_gaps, reference)
        predicted_innovation_id = f"INN_{inn_counter:03d}"
        if predicted_innovation_id in rework_by_innovation_id:
            agg["rework_feedback"] = rework_by_innovation_id[predicted_innovation_id]
        try:
            raw = run_innovation(cluster_id, agg)
            inn = validate_innovation(raw, cluster_id, agg, valid_service_names)
            inn["innovation_id"] = predicted_innovation_id
            if predicted_innovation_id in rework_by_innovation_id:
                feedback = rework_by_innovation_id[predicted_innovation_id]
                inn["human_rework_applied"] = feedback.get("decision") == "accepted"
                inn["auto_rework_applied"] = feedback.get("autonomy") == "auto_apply"
                inn["rework_action_id"] = feedback.get("action_id", "")
                inn["rework_briefing_used"] = (
                    feedback.get("recommendation") or feedback.get("reason") or feedback.get("human_note") or ""
                )
            inn_counter += 1
            innovations.append(order_innovation(inn))
            flag = " [needs_review]" if inn["needs_review"] else ""
            print(f"  {inn['innovation_id']} '{cluster_id}': {inn.get('titel', '')}{flag}")
        except Exception as exc:  # pro-Cluster-Robustheit
            print(f"  FEHLER bei Cluster '{cluster_id}': {exc} — übersprungen")
            continue

    merge_groups = innovation_merge_groups()
    if merge_groups:
        by_id = {item.get("innovation_id"): item for item in innovations}
        for group in merge_groups:
            targets = [str(item) for item in group.get("targets", [])]
            for iid in targets:
                if iid not in by_id:
                    continue
                by_id[iid].setdefault("merge_recommendations", []).append({
                    "merge_group": group.get("target", ""),
                    "targets": targets,
                    "recommendation": group.get("recommendation", ""),
                    "human_accepted": group.get("decision") == "accepted",
                    "auto_applied_by_evaluator": group.get("autonomy") == "auto_apply",
                })

    review_count = sum(1 for i in innovations if i.get("needs_review"))

    output = {
        "schema_version": SCHEMA_VERSION,
        "erstellt_am": now_iso(),
        "modell": MODEL,
        "max_tokens": MAX_TOKENS,
        "input_cluster_count": len(clusters),
        "skipped_cluster_count": skipped,
        "generated_innovation_count": len(innovations),
        "review_count": review_count,
        "innovations": innovations,
    }

    save_json(OUTPUT_PATH, output)
    print(f"\n  Generiert: {len(innovations)} | Übersprungen: {skipped} | Review: {review_count}")
    print(f"Output gespeichert → {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
