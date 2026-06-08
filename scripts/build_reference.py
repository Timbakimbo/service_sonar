"""
Build Reference: Erstellt und aktualisiert eine strukturierte Referenzdatenbank
bestehender sozialer Leistungen für Familien in Deutschland mit Schwerpunkt Bayern.

Backend: Groq (Llama 3.3 70B) — kostenloses Tageskontingent deutlich höher als Gemini Free Tier.

Designprinzipien:
- INKREMENTELL: Bestehende Leistungen bleiben erhalten und werden nicht gelöscht.
- KONTROLLIERTE VOKABULARE für abgedeckte_bedarfe, antragskanaele, bekannte_prozessrisiken
  damit der Gap Analysis Agent semantisch matchen kann.
- SCHEMA-MIGRATION: Alte Felder werden auf deutsches v2-Schema gehoben.
- GAP-AGENT-TAUGLICH: Bedürfnisse, Voraussetzungen, Zugangskanäle, Prozessrisiken werden gespeichert.
- DEDUPLIKATION: über normalisierte Kombination aus Name + zuständige Stelle + Ebene.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

INPUT_PATH = Path("data/raw/scraped_web.json")
OUTPUT_PATH = Path("data/reference/existing_services.json")
LOG_PATH = Path("data/reference/reference_build_log.json")

MODEL = "llama-3.3-70b-versatile"
BATCH_SIZE = 5
TEXT_CHARS_PER_DOC = 3000

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("GROQ_API_KEY fehlt in .env")

client = Groq(api_key=api_key)


# -----------------------------
# Kontrollierte Vokabulare
# -----------------------------

LEISTUNGSARTEN = {
    "Geldleistung",
    "Beratung",
    "Rechtsanspruch",
    "Förderprogramm",
    "Sachleistung",
    "Verfahrensleistung",
    "Informationsangebot",
    "Sonstiges",
}

EBENEN = {
    "Bund",
    "Land Bayern",
    "Kommunal",
    "Sozialversicherung",
    "Freier Träger",
    "Privat",
    "Unklar",
}

# Kontrolliertes Vokabular für abgedeckte_bedarfe — kritisch für Gap Analysis Matching
ABGEDECKTE_BEDARFE = {
    "finanzielle_entlastung",
    "existenzsicherung",
    "erziehungsunterstuetzung",
    "kinderbetreuung",
    "informations_und_beratungsbedarf",
    "teilhabe_bei_behinderung",
    "pflege_entlastung",
    "soziale_teilhabe",
    "rechtliche_absicherung",
    "kinderschutz",
    "wohnraum_sicherung",
    "teilhabe_bei_bildung",
    "schulische_unterstuetzung",
    "psychosoziale_unterstuetzung",
    "gesundheitliche_versorgung",
    "familienplanung_und_gruendung",
    "teilhabe_am_arbeitsleben",
}

ANTRAGSKANAELE = {
    "online",
    "formular",
    "schriftlich",
    "persoenlich",
    "telefonisch",
    "arbeitgeber",
    "krankenkasse",
    "jugendamt",
    "finanzamt",
    "gericht",
    "beratungsstelle",
    "schule",
    "unklar",
}

BEKANNTE_PROZESSRISIKEN = {
    "lange_bearbeitungszeit",
    "unklare_zustaendigkeit",
    "komplexe_nachweise",
    "fristen",
    "hohe_buerokratie",
    "einkommenspruefung",
    "vermoegenspruefung",
    "begrenzte_kapazitaeten",
    "regional_unterschiedliches_angebot",
    "fehlende_information",
    "sprachbarriere",
    "stigma_oder_scham",
    "widerspruch_noetig",
    "fehlende_digitale_kompetenzen",
}


DOMAIN_CONTEXT = """Du extrahierst sozialstaatliche Leistungen für Familien in Deutschland mit Schwerpunkt Bayern.

Inkludiere konkrete bestehende Leistungen, Rechtsansprüche, Beratungsangebote und Förderprogramme für Familien.

Beispiele für relevante Leistungen:
- Elterngeld, ElterngeldPlus, Partnerschaftsbonus
- Bayerisches Familiengeld
- Kindergeld, Kinderzuschlag
- Unterhaltsvorschuss
- Mutterschaftsgeld
- Elternzeit
- Wohngeld für Familien
- Bürgergeld-Mehrbedarfe für Alleinerziehende
- Bildung und Teilhabe
- Kita-Zuschüsse, Beitragsübernahme, Geschwisterermäßigung
- Schwangerschaftsberatung, Erziehungsberatung, Familienberatung
- Leistungen für Kinder mit Behinderung oder Pflegebedarf
- Kinderkrankengeld

Zuständige Stellen können sein:
ZBFS, Familienkasse, Jobcenter, Jugendamt, Krankenkasse, Kommune, Wohngeldstelle,
Finanzamt, Standesamt, Schulamt, Ministerium, Träger der Beratungsstelle.

Nicht extrahieren:
- Datenschutz, Impressum, Cookie-Hinweise
- allgemeine News ohne konkrete Leistung
- reine Forumsbeiträge ohne offizielle Leistungsbeschreibung
- rein technische Verwaltungsinformationen
- doppelte Erwähnungen bereits bekannter Leistungen
"""


# -----------------------------
# Hilfsfunktionen
# -----------------------------


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            item_str = str(item).strip()
            if item_str and item_str not in result:
                result.append(item_str)
        return result
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    return []


def filter_vocabulary(values: list[str], vocabulary: set[str]) -> list[str]:
    """Behält nur Werte die im kontrollierten Vokabular vorkommen."""
    return [v for v in values if v in vocabulary]


def clamp_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def document_hash(doc: dict[str, Any]) -> str:
    raw = f"{doc.get('url', '')}|{doc.get('title', '')}|{doc.get('text', '')[:5000]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_service_key(service: dict[str, Any]) -> str:
    name = normalize_text(service.get("name"))
    stelle = normalize_text(service.get("zustaendige_stelle") or service.get("behoerde"))
    ebene = normalize_text(service.get("ebene"))
    return f"{name}|{stelle}|{ebene}"


def safe_json_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# -----------------------------
# Laden und Migration
# -----------------------------


def load_documents() -> list[dict[str, Any]]:
    docs = safe_json_load(INPUT_PATH, [])
    if not isinstance(docs, list):
        raise ValueError(f"{INPUT_PATH} muss eine JSON-Liste enthalten")
    return docs


def load_existing_reference() -> dict[str, Any]:
    reference = safe_json_load(OUTPUT_PATH, {"schema_version": "2.0-de", "services": []})
    if isinstance(reference, list):
        reference = {"schema_version": "unknown", "services": reference}
    if "services" not in reference or not isinstance(reference["services"], list):
        reference["services"] = []
    return reference


def migrate_service(service: dict[str, Any]) -> dict[str, Any]:
    """Migriert alte Einträge ins deutsche v2-Schema, behält Inhalte."""
    migrated = {
        "name": service.get("name", ""),
        "beschreibung": service.get("beschreibung") or service.get("description") or "",
        "zielgruppe": service.get("zielgruppe") or service.get("target_group") or "",
        "zustaendige_stelle": service.get("zustaendige_stelle") or service.get("behoerde") or "Unklar",
        "leistungsart": service.get("leistungsart") or service.get("art") or "Sonstiges",
        "ebene": service.get("ebene") or service.get("level") or "Unklar",
        "abgedeckte_bedarfe": normalize_list(service.get("abgedeckte_bedarfe")),
        "zugangsvoraussetzungen": normalize_list(service.get("zugangsvoraussetzungen")),
        "antragskanaele": normalize_list(service.get("antragskanaele")),
        "bekannte_prozessrisiken": normalize_list(service.get("bekannte_prozessrisiken")),
        "quellen_urls": normalize_list(service.get("quellen_urls")),
        "konfidenz": clamp_confidence(service.get("konfidenz")),
        "hinzugefuegt_am": service.get("hinzugefuegt_am") or service.get("added_at") or now_iso(),
        "aktualisiert_am": service.get("aktualisiert_am"),
    }
    return normalize_service(migrated)


def normalize_service(service: dict[str, Any]) -> dict[str, Any]:
    """Normalisiert Service-Eintrag und filtert kontrollierte Vokabulare."""
    leistungsart = service.get("leistungsart") or "Sonstiges"
    if leistungsart not in LEISTUNGSARTEN:
        leistungsart = "Sonstiges"

    ebene = service.get("ebene") or "Unklar"
    if ebene not in EBENEN:
        ebene = "Unklar"

    # Kontrollierte Vokabulare filtern — verwerfe Werte die nicht im Set sind
    bedarfe = filter_vocabulary(normalize_list(service.get("abgedeckte_bedarfe")), ABGEDECKTE_BEDARFE)
    kanaele = filter_vocabulary(normalize_list(service.get("antragskanaele")), ANTRAGSKANAELE)
    risiken = filter_vocabulary(normalize_list(service.get("bekannte_prozessrisiken")), BEKANNTE_PROZESSRISIKEN)

    return {
        "name": str(service.get("name", "")).strip(),
        "beschreibung": str(service.get("beschreibung", "")).strip(),
        "zielgruppe": str(service.get("zielgruppe", "")).strip(),
        "zustaendige_stelle": str(service.get("zustaendige_stelle", "Unklar")).strip() or "Unklar",
        "leistungsart": leistungsart,
        "ebene": ebene,
        "abgedeckte_bedarfe": bedarfe,
        "zugangsvoraussetzungen": normalize_list(service.get("zugangsvoraussetzungen")),
        "antragskanaele": kanaele,
        "bekannte_prozessrisiken": risiken,
        "quellen_urls": normalize_list(service.get("quellen_urls")),
        "konfidenz": clamp_confidence(service.get("konfidenz")),
        "hinzugefuegt_am": service.get("hinzugefuegt_am") or now_iso(),
        "aktualisiert_am": service.get("aktualisiert_am"),
    }


def migrate_reference(reference: dict[str, Any]) -> tuple[dict[str, Any], int]:
    old_services = reference.get("services", [])
    migrated_services = []
    changed = 0
    for service in old_services:
        migrated = migrate_service(service)
        migrated_services.append(migrated)
        if service != migrated:
            changed += 1
    reference["schema_version"] = "2.0-de"
    reference["services"] = migrated_services
    reference["letzte_migration_am"] = now_iso()
    return reference, changed


# -----------------------------
# Groq Extraktion
# -----------------------------


def build_docs_text(docs: list[dict[str, Any]]) -> str:
    parts = []
    for i, doc in enumerate(docs, start=1):
        text = str(doc.get("text", ""))[:TEXT_CHARS_PER_DOC]
        parts.append(
            f"--- Dokument {i} ---\n"
            f"URL: {doc.get('url', '')}\n"
            f"Titel: {doc.get('title', '')}\n"
            f"Inhalt:\n{text}\n"
        )
    return "\n".join(parts)


def build_existing_summary(existing_services: list[dict[str, Any]]) -> str:
    if not existing_services:
        return "Keine bereits bekannten Leistungen."
    lines = ["Bereits bekannte Leistungen, NICHT erneut ausgeben:"]
    for service in existing_services:
        lines.append(f"- {service.get('name', '')} | {service.get('zustaendige_stelle', '')} | {service.get('ebene', '')}")
    return "\n".join(lines)


def extract_services_from_batch(
    docs: list[dict[str, Any]],
    existing_services: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    docs_text = build_docs_text(docs)
    existing_summary = build_existing_summary(existing_services)

    prompt = f"""{DOMAIN_CONTEXT}

Hier sind {len(docs)} Dokumente:

{docs_text}

{existing_summary}

Aufgabe:
Extrahiere ALLE konkreten Familienleistungen die in den Dokumenten genannt werden — auch wenn sie nur am Rande erwähnt sind, nicht nur das Hauptthema. Wenn ein Forum-Post über Wohngeld nebenbei Unterhaltsvorschuss erwähnt, extrahiere beide. Sei großzügig: jede konkrete benannte Leistung kommt rein, auch wenn sie nur in einem Satz steht.

Beispiele für Leistungen die in Familienforen oft erwähnt werden und alle extrahiert werden sollen:
Wohngeld, Mutterschaftsgeld, Unterhaltsvorschuss, Kinderkrankengeld, Pflegegrad,
Pflegegeld, Blindengeld, Schwerbehindertenausweis, Bürgergeld, Bildungspaket,
Schuldnerberatung, Familienberatung, Erziehungsberatung, Hilfen zur Erziehung,
Eingliederungshilfe, Kita-Gebührenermäßigung, Geschwisterermäßigung.

Bereits bekannte Leistungen NICHT erneut ausgeben (siehe Liste oben).

KONTROLLIERTE VOKABULARE — du MUSST diese Werte verwenden:

leistungsart (genau einer): {sorted(LEISTUNGSARTEN)}

ebene (genau einer): {sorted(EBENEN)}

abgedeckte_bedarfe (Liste von 1-5 Werten aus diesem Set):
{sorted(ABGEDECKTE_BEDARFE)}

antragskanaele (Liste von 1-4 Werten aus diesem Set):
{sorted(ANTRAGSKANAELE)}

bekannte_prozessrisiken (Liste von 0-4 Werten aus diesem Set):
{sorted(BEKANNTE_PROZESSRISIKEN)}

zugangsvoraussetzungen darf Freitext sein (knappe deutsche Stichpunkte).

WICHTIG:
- Keine doppelten Leistungen ausgeben.
- Keine generischen Namen wie "Leistung für Familien".
- Werte für abgedeckte_bedarfe, antragskanaele, bekannte_prozessrisiken MÜSSEN exakt aus dem Set kommen (Schreibweise!).
- Wenn unklar, setze zustaendige_stelle="Unklar".
- konfidenz: 0.0-1.0, wie sicher der Eintrag ist.

Antworte NUR mit validem JSON, exakt in diesem Format:
{{
  "services": [
    {{
      "name": "Offizieller Name der Leistung",
      "beschreibung": "1-2 Sätze.",
      "zielgruppe": "Wer anspruchsberechtigt ist.",
      "zustaendige_stelle": "Zuständige Stelle",
      "leistungsart": "...",
      "ebene": "...",
      "abgedeckte_bedarfe": ["..."],
      "zugangsvoraussetzungen": ["..."],
      "antragskanaele": ["..."],
      "bekannte_prozessrisiken": ["..."],
      "quellen_urls": ["URL"],
      "konfidenz": 0.0
    }}
  ]
}}

Wenn keine neuen Leistungen gefunden werden: {{"services": []}}
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        parsed = json.loads(response.choices[0].message.content)
        services = parsed.get("services", [])
        if not isinstance(services, list):
            return []
        return [normalize_service(service) for service in services if isinstance(service, dict)]
    except Exception as exc:
        print(f"  Fehler im Groq-Batch: {exc}")
        return []


# -----------------------------
# Merge und Log
# -----------------------------


def merge_services(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing_keys = {make_service_key(service) for service in existing}
    added = []
    timestamp = now_iso()
    for service in new:
        service = normalize_service(service)
        if not service.get("name"):
            continue
        key = make_service_key(service)
        if key in existing_keys:
            continue
        service["hinzugefuegt_am"] = service.get("hinzugefuegt_am") or timestamp
        service["aktualisiert_am"] = timestamp
        existing.append(service)
        existing_keys.add(key)
        added.append(service)
    return existing, added


def load_log() -> dict[str, Any]:
    log = safe_json_load(LOG_PATH, {"verarbeitete_dokument_hashes": [], "runs": []})
    if "verarbeitete_dokument_hashes" not in log:
        log["verarbeitete_dokument_hashes"] = []
    if "runs" not in log:
        log["runs"] = []
    return log


def save_run_log(log, processed_hashes, docs_count, new_count, total_count) -> None:
    known_hashes = set(log.get("verarbeitete_dokument_hashes", []))
    known_hashes.update(processed_hashes)
    log["verarbeitete_dokument_hashes"] = sorted(known_hashes)
    log["runs"].append({
        "zeitpunkt": now_iso(),
        "verarbeitete_dokumente": docs_count,
        "neu_hinzugefuegte_leistungen": new_count,
        "leistungen_gesamt": total_count,
        "modell": MODEL,
        "batch_size": BATCH_SIZE,
    })
    save_json(LOG_PATH, log)


# -----------------------------
# Run
# -----------------------------


def run(force_all: bool = False) -> None:
    print("Build Reference gestartet...")
    print(f"Backend: Groq ({MODEL})")

    docs = load_documents()
    print(f"  {len(docs)} Web-Dokumente geladen")

    reference = load_existing_reference()
    reference, migrated_count = migrate_reference(reference)
    existing_services = reference.get("services", [])
    print(f"  {len(existing_services)} bestehende Leistungen geladen")
    print(f"  {migrated_count} bestehende Leistungen ins deutsche v2-Schema migriert")

    log = load_log()
    already_processed = set(log.get("verarbeitete_dokument_hashes", []))

    docs_with_hashes = [(doc, document_hash(doc)) for doc in docs]
    if force_all:
        docs_to_process = docs_with_hashes
        print("  Force-Modus aktiv: alle Dokumente werden erneut verarbeitet")
    else:
        docs_to_process = [(doc, h) for doc, h in docs_with_hashes if h not in already_processed]
        print(f"  {len(docs_to_process)} neue/ungeprüfte Dokumente zu verarbeiten")

    total_batches = (len(docs_to_process) + BATCH_SIZE - 1) // BATCH_SIZE if docs_to_process else 0
    total_new = 0
    processed_hashes = []

    for start in range(0, len(docs_to_process), BATCH_SIZE):
        batch_num = start // BATCH_SIZE + 1
        batch_pairs = docs_to_process[start:start + BATCH_SIZE]
        batch_docs = [doc for doc, _ in batch_pairs]
        batch_hashes = [h for _, h in batch_pairs]

        print(f"\nBatch {batch_num}/{total_batches} — {len(batch_docs)} Dokumente...")
        extracted = extract_services_from_batch(batch_docs, existing_services)
        print(f"  {len(extracted)} Leistungen extrahiert vor Dedup")

        existing_services, added = merge_services(existing_services, extracted)
        total_new += len(added)
        processed_hashes.extend(batch_hashes)

        if added:
            for service in added:
                print(f"    + {service.get('name')} ({service.get('zustaendige_stelle')}, {service.get('ebene')})")
                print(f"      Bedarfe: {service.get('abgedeckte_bedarfe')}")
        else:
            print("    Keine neuen Leistungen hinzugefügt")

    reference["schema_version"] = "2.0-de"
    reference["services"] = existing_services
    reference["aktualisiert_am"] = now_iso()

    save_json(OUTPUT_PATH, reference)
    save_run_log(log, processed_hashes, len(docs_to_process), total_new, len(existing_services))

    print("\n=== Referenz aktualisiert ===")
    print(f"  Neue Leistungen hinzugefügt: {total_new}")
    print(f"  Leistungen gesamt: {len(existing_services)}")
    print(f"  Gespeichert in: {OUTPUT_PATH}")


if __name__ == "__main__":
    run(force_all=False)