"""
Migration Script: Reichert bestehende Leistungen in existing_services.json mit
Gap-Agent-relevanten Feldern an.

Ziel:
- Keine neuen Leistungen extrahieren
- Keine Leistungen löschen
- Bestehende Basisfelder behalten
- Nur leere/fehlende Felder ergänzen:
  - abgedeckte_bedarfe
  - zugangsvoraussetzungen
  - antragskanaele
  - bekannte_prozessrisiken
  - konfidenz
  - aktualisiert_am

Warum separat?
- build_reference.py bleibt für Extraktion neuer Leistungen zuständig
- diese Datei ist ein einmaliger Migrations-/Anreicherungsschritt

Backend: Groq (Llama 3.3 70B) — kostenloses Tageskontingent deutlich höher als Gemini Free Tier.

Ausführen:
    python scripts/migrate_reference_needs.py

Vorher empfohlen:
    cp data/reference/existing_services.json data/reference/existing_services_backup.json
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

REFERENCE_PATH = Path("data/reference/existing_services.json")
BACKUP_PATH = Path("data/reference/existing_services_before_migration.json")
LOG_PATH = Path("data/reference/reference_migration_log.json")

MODEL = "llama-3.3-70b-versatile"
SLEEP_SECONDS = 1.0
MAX_SERVICES = None  # Für Testlauf z.B. 5 setzen, danach wieder None

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

ERLAUBTE_LEISTUNGSARTEN = {
    "Geldleistung",
    "Beratung",
    "Rechtsanspruch",
    "Förderprogramm",
    "Sachleistung",
    "Verfahrensleistung",
    "Sonstiges",
    "Unklar",
}

ERLAUBTE_EBENEN = {
    "Bund",
    "Land Bayern",
    "Kommunal",
    "Sozialversicherung",
    "Unklar",
    "Privat",
}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def service_key(service: dict) -> str:
    name = str(service.get("name", "")).strip().lower()
    stelle = str(service.get("zustaendige_stelle", service.get("behoerde", ""))).strip().lower()
    return f"{name}|{stelle}"


def ensure_schema(service: dict) -> dict:
    """Sichert deutsches v2-Schema, ohne bestehende Inhalte zu überschreiben."""
    mapping = {
        "behoerde": "zustaendige_stelle",
        "art": "leistungsart",
        "added_at": "hinzugefuegt_am",
    }
    for old, new in mapping.items():
        if new not in service and old in service:
            service[new] = service.get(old)

    service.setdefault("beschreibung", service.get("description", ""))
    service.setdefault("zielgruppe", service.get("target_group", ""))
    service.setdefault("zustaendige_stelle", "Unklar")
    service.setdefault("leistungsart", "Unklar")
    service.setdefault("ebene", "Unklar")
    service.setdefault("abgedeckte_bedarfe", [])
    service.setdefault("zugangsvoraussetzungen", [])
    service.setdefault("antragskanaele", [])
    service.setdefault("bekannte_prozessrisiken", [])
    service.setdefault("quellen_urls", [])
    service.setdefault("konfidenz", None)
    service.setdefault("hinzugefuegt_am", now_iso())
    service.setdefault("aktualisiert_am", None)

    if service.get("leistungsart") not in ERLAUBTE_LEISTUNGSARTEN:
        service["leistungsart"] = "Unklar"
    if service.get("ebene") not in ERLAUBTE_EBENEN:
        service["ebene"] = "Unklar"

    return service


def needs_enrichment(service: dict) -> bool:
    """Nur anreichern, wenn zentrale Gap-Felder fehlen oder leer sind."""
    return not service.get("abgedeckte_bedarfe")


def build_prompt(service: dict) -> str:
    return f"""
Du reicherst eine bestehende Referenzdatenbank sozialstaatlicher Leistungen für Familien in Deutschland/Bayern an.

Wichtig:
- Du erfindest KEINE neue Leistung.
- Du veränderst den Namen NICHT.
- Du ergänzt nur strukturierte Felder für den späteren Gap Analysis Agent.
- Beratungen und Rechtsansprüche zählen als Leistungen, wenn sie eigenständigen fachlichen Nutzen haben.
- Reine Kontaktwege, Terminbuchungen, Formulare oder Portale sind keine eigenständige inhaltliche Leistung; wenn die gegebene Leistung so etwas ist, markiere die Bedarfe entsprechend eng als Zugang/Kommunikation.
- Private Angebote dürfen als privat erkennbar bleiben, aber dürfen nicht als staatliche Vollabdeckung formuliert werden.

Bestehende Leistung:
Name: {service.get('name', '')}
Beschreibung: {service.get('beschreibung', '')}
Zielgruppe: {service.get('zielgruppe', '')}
Zuständige Stelle: {service.get('zustaendige_stelle', '')}
Leistungsart: {service.get('leistungsart', '')}
Ebene: {service.get('ebene', '')}

Ergänze präzise:

1. abgedeckte_bedarfe:
   2-6 kurze Begriffe, die beschreiben, welchen Bürgerbedarf diese Leistung deckt.
   Beispiele:
   - finanzielle_entlastung
   - einkommensersatz_nach_geburt
   - kinderbetreuung_finanzieren
   - erziehungsunterstuetzung
   - pflege_entlastung
   - teilhabe_bei_behinderung
   - rechtliche_absicherung
   - informations_und_beratungsbedarf

2. zugangsvoraussetzungen:
   2-6 konkrete Voraussetzungen, soweit aus der Beschreibung ableitbar.
   Wenn unklar, [] oder ["unklar"].

3. antragskanaele:
   Nur falls ableitbar: online, formular, schriftlich, persoenlich, telefonisch, arbeitgeber, krankenkasse, jugendamt, finanzamt, gericht, unklar.

4. bekannte_prozessrisiken:
   Typische Zugangshürden oder Risiken, die bei dieser Leistungsart plausibel sind.
   Beispiele:
   - lange_bearbeitungszeit
   - komplexe_nachweise
   - unklare_zustaendigkeit
   - einkommenspruefung
   - fristen
   - widerspruch_noetig
   - hohe_buerokratie
   Wenn nichts spezifisch plausibel ist: []

5. konfidenz:
   Zahl zwischen 0.0 und 1.0, wie sicher die Ergänzung ist.

Antworte NUR mit validem JSON (keine Markdown-Fences, kein Text drumherum):
{{
  "abgedeckte_bedarfe": [],
  "zugangsvoraussetzungen": [],
  "antragskanaele": [],
  "bekannte_prozessrisiken": [],
  "konfidenz": 0.0
}}
""".strip()


def enrich_service(service: dict) -> dict | None:
    prompt = build_prompt(service)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    data = json.loads(response.choices[0].message.content)

    return {
        "abgedeckte_bedarfe": data.get("abgedeckte_bedarfe", []),
        "zugangsvoraussetzungen": data.get("zugangsvoraussetzungen", []),
        "antragskanaele": data.get("antragskanaele", []),
        "bekannte_prozessrisiken": data.get("bekannte_prozessrisiken", []),
        "konfidenz": data.get("konfidenz", None),
    }


def apply_enrichment(service: dict, enrichment: dict) -> dict:
    # Nur leere Felder füllen, bestehende manuelle Werte nicht überschreiben.
    for field in [
        "abgedeckte_bedarfe",
        "zugangsvoraussetzungen",
        "antragskanaele",
        "bekannte_prozessrisiken",
    ]:
        if not service.get(field):
            value = enrichment.get(field, [])
            service[field] = value if isinstance(value, list) else []

    if service.get("konfidenz") is None:
        service["konfidenz"] = enrichment.get("konfidenz")

    service["aktualisiert_am"] = now_iso()
    return service


def run() -> None:
    print("Reference Migration/Anreicherung gestartet...")
    print(f"Backend: Groq ({MODEL})")

    reference = load_json(REFERENCE_PATH, {"services": []})
    services = [ensure_schema(s) for s in reference.get("services", [])]
    log = load_json(LOG_PATH, {"processed_keys": [], "errors": []})
    processed_keys = set(log.get("processed_keys", []))

    if REFERENCE_PATH.exists() and not BACKUP_PATH.exists():
        save_json(BACKUP_PATH, reference)
        print(f"  Backup erstellt: {BACKUP_PATH}")

    candidates = []
    for idx, service in enumerate(services):
        key = service_key(service)
        if needs_enrichment(service) and key not in processed_keys:
            candidates.append((idx, key, service))

    if MAX_SERVICES is not None:
        candidates = candidates[:MAX_SERVICES]

    print(f"  Leistungen gesamt: {len(services)}")
    print(f"  Zu ergänzen: {len(candidates)}")

    enriched_count = 0

    for n, (idx, key, service) in enumerate(candidates, start=1):
        print(f"\n[{n}/{len(candidates)}] {service.get('name')} ...")
        try:
            enrichment = enrich_service(service)
            services[idx] = apply_enrichment(service, enrichment)
            processed_keys.add(key)
            enriched_count += 1

            print(f"  Bedarfe: {services[idx].get('abgedeckte_bedarfe')}")

            reference["services"] = services
            reference["schema_version"] = "2.0-de"
            reference["aktualisiert_am"] = now_iso()
            log["processed_keys"] = sorted(processed_keys)
            log["last_run_at"] = now_iso()

            save_json(REFERENCE_PATH, reference)
            save_json(LOG_PATH, log)

            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            msg = str(e)
            print(f"  Fehler: {msg}")
            log.setdefault("errors", []).append({
                "service_key": key,
                "name": service.get("name"),
                "error": msg,
                "timestamp": now_iso(),
            })
            save_json(LOG_PATH, log)

            if "rate_limit" in msg.lower() or "429" in msg or "quota" in msg.lower():
                print("  Groq-Limit erreicht. Stoppe sauber, bisherige Ergebnisse sind gespeichert.")
                break

    print("\n=== Migration abgeschlossen/pausiert ===")
    print(f"  Ergänzt in diesem Run: {enriched_count}")
    print(f"  Datei: {REFERENCE_PATH}")
    print(f"  Log: {LOG_PATH}")


if __name__ == "__main__":
    run()