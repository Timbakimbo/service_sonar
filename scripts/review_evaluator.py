"""Interactive human review of Evaluator recommendations.

The script records decisions only. It never starts agents or applies non-keyword
changes. Accepted keyword decisions are consumed on the next manually started
Source Discovery or Reddit run.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


EVALUATOR_PATH = Path("data/evaluation/evaluator_output.json")
OUTPUT_PATH = Path("data/evaluation/human_decisions.json")
SCHEMA_VERSION = "1.0-de"
SECTION_CHOICES = ("all", "keywords", "rework", "topics", "reclassify", "merge")


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Nicht gefunden: {path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"JSON-Objekt erwartet: {path}")
    return data


def collect_actions(evaluator: dict, section: str = "all") -> list[dict]:
    actions: list[dict] = []
    aggregate = evaluator.get("aggregierte_aktionen", {})

    if section in ("all", "keywords"):
        feedback = evaluator.get("keyword_feedback", {})
        for keyword in feedback.get("neue_keywords_vorgeschlagen", []):
            actions.append({
                "action_type": "keyword_add",
                "target_agent": "source-discovery/reddit-scraper",
                "target": keyword,
                "recommendation": f"Keyword hinzufügen: {keyword}",
            })
        for keyword in feedback.get("schwache_keywords", []):
            actions.append({
                "action_type": "keyword_remove",
                "target_agent": "source-discovery/reddit-scraper",
                "target": keyword,
                "recommendation": f"Schwaches Keyword entfernen: {keyword}",
            })

    if section in ("all", "rework"):
        by_id = {item.get("innovation_id"): item for item in evaluator.get("innovation_evaluations", [])}
        for innovation_id in aggregate.get("regenerieren", []):
            evaluation = by_id.get(innovation_id, {})
            briefing = evaluation.get("rework_briefing") or evaluation.get("begruendung", "")
            actions.append({
                "action_type": "innovation_rework",
                "target_agent": "innovation",
                "target": innovation_id,
                "recommendation": briefing,
            })

    if section in ("all", "topics"):
        by_id = {str(item.get("topic_id")): item for item in evaluator.get("topic_evaluations", [])}
        for topic_id in aggregate.get("topics_entfernen", []):
            evaluation = by_id.get(str(topic_id), {})
            actions.append({
                "action_type": "topic_remove",
                "target_agent": "gap-analysis",
                "target": str(topic_id),
                "recommendation": evaluation.get("begruendung", "Topic entfernen"),
            })

    if section in ("all", "reclassify"):
        by_id = {str(item.get("topic_id")): item for item in evaluator.get("gap_evaluations", [])}
        for topic_id in aggregate.get("reklassifizieren", []):
            evaluation = by_id.get(str(topic_id), {})
            actions.append({
                "action_type": "gap_reclassify",
                "target_agent": "gap-analysis",
                "target": str(topic_id),
                "recommendation": evaluation.get("begruendung", "Gap reklassifizieren"),
                "proposed_value": evaluation.get("vorgeschlagene_klassifikation"),
            })

    if section in ("all", "merge"):
        for index, innovation_ids in enumerate(aggregate.get("konvergenz_zusammenfuehren", []), 1):
            actions.append({
                "action_type": "innovation_merge",
                "target_agent": "innovation",
                "target": f"merge_group_{index}",
                "targets": innovation_ids,
                "recommendation": "Konvergente Innovationen fachlich zusammenführen",
            })
    return actions


def ask_decision(action: dict, input_fn: Callable[[str], str] = input) -> tuple[str, str]:
    print(f"\n[{action['action_type']}] {action['target']}")
    if action.get("targets"):
        print("Betroffen: " + ", ".join(action["targets"]))
    print("Empfehlung: " + str(action.get("recommendation", "")))
    if action.get("proposed_value"):
        print("Vorgeschlagener Wert: " + str(action["proposed_value"]))
    while True:
        answer = input_fn("Akzeptieren [y], ablehnen [n], vertagen [s]? ").strip().lower()
        if answer in ("y", "j", "yes", "ja"):
            decision = "accepted"
            break
        if answer in ("n", "no", "nein"):
            decision = "rejected"
            break
        if answer in ("s", "skip", "später", "spaeter"):
            decision = "deferred"
            break
        print("Bitte y, n oder s eingeben.")
    note = input_fn("Optionale Notiz (Enter = keine): ").strip()
    return decision, note


def review(evaluator: dict, section: str, input_fn: Callable[[str], str] = input) -> list[dict]:
    actions = collect_actions(evaluator, section)
    if not actions:
        print("Keine Aktionen in diesem Bereich.")
        return []
    print(f"{len(actions)} Evaluator-Aktion(en) zur menschlichen Entscheidung.")
    decisions = []
    for action in actions:
        decision, note = ask_decision(action, input_fn)
        decisions.append({**action, "decision": decision, "human_note": note})
    return decisions


def save_decisions(output_path: Path, evaluator_path: Path, section: str, decisions: list[dict]) -> None:
    existing_decisions: list[dict] = []
    reviewed_sections: list[str] = []
    if output_path.is_file():
        try:
            existing = load_json(output_path)
            existing_decisions = existing.get("decisions", [])
            reviewed_sections = existing.get("reviewed_sections", [])
            if not reviewed_sections and existing.get("reviewed_section"):
                reviewed_sections = [existing["reviewed_section"]]
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def key(item: dict) -> tuple[str, str]:
        return str(item.get("action_type", "")), str(item.get("target", ""))

    merged = {key(item): item for item in existing_decisions}
    merged.update({key(item): item for item in decisions})
    all_decisions = list(merged.values())
    sections = list(dict.fromkeys([*reviewed_sections, section]))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_evaluator_output": str(evaluator_path),
        "reviewed_sections": sections,
        "decisions": all_decisions,
        "summary": {
            status: sum(1 for item in all_decisions if item["decision"] == status)
            for status in ("accepted", "rejected", "deferred")
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluator-Aktionen interaktiv akzeptieren oder ablehnen.")
    parser.add_argument("--section", choices=SECTION_CHOICES, default="all")
    parser.add_argument("--input", type=Path, default=EVALUATOR_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    try:
        evaluator = load_json(args.input)
        decisions = review(evaluator, args.section)
        save_decisions(args.output, args.input, args.section, decisions)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FEHLER: {exc}")
        return 1

    print(f"\nEntscheidungen gespeichert → {args.output}")
    print("Keine Stage wurde automatisch gestartet.")
    if args.section in ("all", "keywords"):
        print("Akzeptierte Keyword-Entscheidungen gelten beim nächsten manuellen Discovery-/Reddit-Lauf.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
