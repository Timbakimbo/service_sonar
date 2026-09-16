"""Interactive human review of Evaluator recommendations.

The script records human decisions only. It never starts agents. Auto-apply
actions are consumed directly by target agents on the next manual run.
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
SECTION_CHOICES = ("all", "keywords", "rework", "topics", "reclassify", "merge", "real-gaps")


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Nicht gefunden: {path}")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"JSON-Objekt erwartet: {path}")
    return data


def action_key(item: dict) -> str:
    return str(item.get("action_id", ""))


def validate_evaluator_provenance(evaluator: dict) -> None:
    run_id = str(evaluator.get("evaluator_run_id", "")).strip()
    if not run_id:
        raise ValueError(
            "LEGACY EVALUATOR OUTPUT - zuerst einen frischen Evaluator-Lauf ausfuehren"
        )
    actions = evaluator.get("aktionen", [])
    if not isinstance(actions, list):
        raise ValueError("Evaluator-Aktionen muessen eine Liste sein")
    required = {
        "action_id", "action_type", "evaluator_run_id", "stable_target",
        "target", "target_agent", "autonomy",
    }
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise ValueError(f"Evaluator-Aktion {index} ist kein Objekt")
        missing = [field for field in required if not str(action.get(field, "")).strip()]
        if missing or str(action.get("evaluator_run_id")) != run_id:
            detail = ", ".join(missing) if missing else "evaluator_run_id passt nicht"
            raise ValueError(
                f"Evaluator-Aktion {index} ohne gueltige Provenienz ({detail}); "
                "frischen Evaluator-Lauf ausfuehren"
            )


def decision_matches_current(item: dict, evaluator: dict) -> bool:
    run_id = str(evaluator.get("evaluator_run_id", ""))
    current = {
        action_key(action): action
        for action in evaluator.get("aktionen", [])
        if isinstance(action, dict) and action_key(action)
    }
    action = current.get(action_key(item))
    return bool(
        run_id
        and action
        and str(item.get("evaluator_run_id", "")) == run_id
        and str(item.get("stable_target", "")) == str(action.get("stable_target", ""))
        and str(item.get("action_type", "")) == str(action.get("action_type", ""))
    )


def load_decision_keys(path: Path, evaluator: dict) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return set()
    return {
        action_key(item)
        for item in data.get("decisions", [])
        if item.get("decision") in ("accepted", "rejected")
        and decision_matches_current(item, evaluator)
    }


def stale_decision_count(path: Path, evaluator: dict) -> int:
    if not path.is_file():
        return 0
    try:
        data = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return 0
    return sum(
        1 for item in data.get("decisions", [])
        if not decision_matches_current(item, evaluator)
    )


def section_matches(action: dict, section: str) -> bool:
    if section == "all":
        return True
    return {
        "keywords": {"keyword_add", "keyword_remove"},
        "rework": {"innovation_rework"},
        "topics": {"topic_remove"},
        "reclassify": {"gap_reclassify"},
        "merge": {"innovation_merge"},
        "real-gaps": {"real_gap_review"},
    }.get(section, set()).__contains__(action.get("action_type"))


def collect_actions(
    evaluator: dict,
    section: str = "all",
    include_auto: bool = False,
    include_suggestions: bool = False,
    only_open: bool = False,
    decisions_path: Path = OUTPUT_PATH,
) -> list[dict]:
    normalized = evaluator.get("aktionen", [])
    if isinstance(normalized, list) and normalized:
        actions = []
        decided = load_decision_keys(decisions_path, evaluator) if only_open else set()
        for action in normalized:
            autonomy = action.get("autonomy", "human_required")
            if autonomy == "auto_apply" and not include_auto:
                continue
            if autonomy == "suggestion_only" and not include_suggestions:
                continue
            if not section_matches(action, section):
                continue
            if only_open and action_key(action) in decided:
                continue
            actions.append(action)
        return actions

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
    if only_open:
        decided = load_decision_keys(decisions_path, evaluator)
        actions = [action for action in actions if action_key(action) not in decided]
    return actions


def ask_decision(action: dict, input_fn: Callable[[str], str] = input) -> tuple[str, str]:
    print(f"\n[{action['action_type']}] {action['target']}")
    if action.get("stable_target"):
        print("Stabiles Ziel: " + str(action["stable_target"]))
    if action.get("autonomy"):
        print("Autonomie: " + str(action.get("autonomy")))
    if action.get("risk"):
        print("Risiko: " + str(action.get("risk")))
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


def review(
    evaluator: dict,
    section: str,
    input_fn: Callable[[str], str] = input,
    include_auto: bool = False,
    include_suggestions: bool = False,
    only_open: bool = False,
    decisions_path: Path = OUTPUT_PATH,
) -> list[dict]:
    actions = collect_actions(
        evaluator,
        section,
        include_auto=include_auto,
        include_suggestions=include_suggestions,
        only_open=only_open,
        decisions_path=decisions_path,
    )
    if not actions:
        print("Keine Aktionen in diesem Bereich.")
        return []
    print(f"{len(actions)} Evaluator-Aktion(en) zur menschlichen Entscheidung.")
    decisions = []
    for action in actions:
        decision, note = ask_decision(action, input_fn)
        decisions.append({
            **action,
            "decision": decision,
            "human_reason": note,
            "human_note": note,
            "application_status": {
                "accepted": "approved_for_manual_consumption",
                "rejected": "refused",
                "deferred": "deferred",
            }[decision],
            "conflict_reason": note if decision == "rejected" else "",
        })
    return decisions


def save_decisions(
    output_path: Path,
    evaluator_path: Path,
    section: str,
    decisions: list[dict],
    evaluator: dict | None = None,
) -> None:
    evaluator = evaluator or load_json(evaluator_path)
    evaluator_run_id = str(evaluator.get("evaluator_run_id", ""))
    if not evaluator_run_id:
        raise ValueError("Evaluator-Output ohne evaluator_run_id; zuerst Evaluator neu ausfuehren")
    existing_decisions: list[dict] = []
    reviewed_sections: list[str] = []
    if output_path.is_file():
        try:
            existing = load_json(output_path)
            if str(existing.get("evaluator_run_id", "")) == evaluator_run_id:
                existing_decisions = existing.get("decisions", [])
                reviewed_sections = existing.get("reviewed_sections", [])
                if not reviewed_sections and existing.get("reviewed_section"):
                    reviewed_sections = [existing["reviewed_section"]]
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def key(item: dict) -> str:
        return str(item.get("action_id", ""))

    merged = {key(item): item for item in existing_decisions}
    merged.update({key(item): item for item in decisions})
    all_decisions = list(merged.values())
    sections = list(dict.fromkeys([*reviewed_sections, section]))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_evaluator_output": str(evaluator_path),
        "evaluator_run_id": evaluator_run_id,
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
    parser.add_argument("--include-auto", action="store_true", help="Auto-Apply-Aktionen ebenfalls anzeigen")
    parser.add_argument("--include-suggestions", action="store_true", help="Suggestion-only-Aktionen ebenfalls anzeigen")
    parser.add_argument(
        "--only-open", action="store_true",
        help="Nur unentschiedene oder vertagte human_required Aktionen anzeigen",
    )
    args = parser.parse_args()

    try:
        evaluator = load_json(args.input)
        validate_evaluator_provenance(evaluator)
        stale_count = stale_decision_count(args.output, evaluator)
        if stale_count:
            print(
                f"WARNUNG: {stale_count} bestehende Entscheidung(en) gehoeren nicht zum "
                "aktuellen Evaluator-Lauf und werden ignoriert."
            )
        decisions = review(
            evaluator,
            args.section,
            include_auto=args.include_auto,
            include_suggestions=args.include_suggestions,
            only_open=args.only_open,
            decisions_path=args.output,
        )
        save_decisions(args.output, args.input, args.section, decisions, evaluator=evaluator)
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
