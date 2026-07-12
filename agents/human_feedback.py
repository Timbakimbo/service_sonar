"""Read-only helpers for provenance-bound Evaluator feedback.

Only decisions for the current ``evaluator_run_id`` and current ``action_id``
may affect a later manually started stage. Legacy and stale decisions remain
visible for audit purposes but are never consumed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EVALUATOR_PATH = Path("data/evaluation/evaluator_output.json")
HUMAN_DECISIONS_PATH = Path("data/evaluation/human_decisions.json")
DECISION_FIELDS = {
    "decision",
    "human_reason",
    "human_note",
    "decided_at",
    "reviewer",
    "application_status",
    "conflict_reason",
}


def load_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def evaluator_actions(evaluator_path: Path = EVALUATOR_PATH) -> list[dict]:
    data = load_json(evaluator_path, {})
    actions = data.get("aktionen", [])
    return actions if isinstance(actions, list) else []


def evaluator_provenance_valid(evaluator: dict) -> bool:
    run_id = str(evaluator.get("evaluator_run_id", "")).strip()
    actions = evaluator.get("aktionen", [])
    required = {
        "action_id", "action_type", "evaluator_run_id", "stable_target",
        "target", "target_agent", "autonomy",
    }
    return bool(run_id) and isinstance(actions, list) and all(
        isinstance(action, dict)
        and all(str(action.get(field, "")).strip() for field in required)
        and str(action.get("evaluator_run_id")) == run_id
        for action in actions
    )


def decision_diagnostics(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> dict[str, Any]:
    evaluator = load_json(evaluator_path, {})
    decisions = load_json(decisions_path, {})
    run_id = str(evaluator.get("evaluator_run_id", ""))
    actions = evaluator.get("aktionen", []) if isinstance(evaluator.get("aktionen"), list) else []
    current_by_id = {
        str(action.get("action_id")): action
        for action in actions
        if action.get("action_id")
    }
    matched: dict[str, dict] = {}
    stale: list[dict] = []
    for decision in decisions.get("decisions", []) if isinstance(decisions, dict) else []:
        action_id = str(decision.get("action_id", ""))
        action = current_by_id.get(action_id)
        same_run = bool(run_id) and str(decision.get("evaluator_run_id", "")) == run_id
        same_target = bool(action) and str(decision.get("stable_target", "")) == str(
            action.get("stable_target", "")
        )
        same_type = bool(action) and str(decision.get("action_type", "")) == str(
            action.get("action_type", "")
        )
        if same_run and action and same_target and same_type:
            allowed_decision = {
                field: decision[field]
                for field in DECISION_FIELDS
                if field in decision
            }
            matched[action_id] = {
                **action,
                **allowed_decision,
                "human_decision": allowed_decision,
            }
        else:
            stale.append(decision)
    return {
        "evaluator_run_id": run_id,
        "matched": matched,
        "stale": stale,
        "stale_count": len(stale),
    }


def report_stale_decisions(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> int:
    count = int(decision_diagnostics(evaluator_path, decisions_path)["stale_count"])
    if count:
        print(
            f"  WARNUNG: {count} veraltete Human Decision(s) ohne passende "
            "Evaluator-Provenienz werden ignoriert."
        )
    return count


def accepted_human_decisions(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> list[dict]:
    diagnostics = decision_diagnostics(evaluator_path, decisions_path)
    return [
        item
        for item in diagnostics["matched"].values()
        if item.get("decision") == "accepted"
        and item.get("autonomy") == "human_required"
    ]


def auto_apply_actions(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> list[dict]:
    """Return current auto actions unless a matching decision rejected/deferred them."""
    evaluator = load_json(evaluator_path, {})
    if not evaluator_provenance_valid(evaluator):
        return []
    diagnostics = decision_diagnostics(evaluator_path, decisions_path)
    matched = diagnostics["matched"]
    eligible = []
    for action in evaluator_actions(evaluator_path):
        if action.get("autonomy") != "auto_apply":
            continue
        decision = matched.get(str(action.get("action_id", "")), {})
        if decision.get("decision") in {"rejected", "deferred"}:
            continue
        eligible.append(action)
    return eligible


def accepted_or_auto_actions(
    action_type: str | None = None,
    target_agent: str | None = None,
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> list[dict]:
    actions = [
        *accepted_human_decisions(evaluator_path, decisions_path),
        *auto_apply_actions(evaluator_path, decisions_path),
    ]
    if action_type is not None:
        actions = [a for a in actions if a.get("action_type") == action_type]
    if target_agent is not None:
        actions = [a for a in actions if a.get("target_agent") == target_agent]
    return actions


def topic_removal_actions(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> list[dict]:
    return accepted_or_auto_actions("topic_remove", "gap-analysis", evaluator_path, decisions_path)


def topic_removals(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> set[str]:
    return {
        str(action.get("topic_id") or action.get("target"))
        for action in topic_removal_actions(evaluator_path, decisions_path)
    }


def gap_reclassifications(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for action in accepted_or_auto_actions(
        "gap_reclassify", "gap-analysis", evaluator_path, decisions_path
    ):
        topic_id = str(action.get("topic_id") or action.get("target", ""))
        proposed = action.get("proposed_value")
        if topic_id and proposed:
            out[topic_id] = action
    return out


def innovation_rework_briefings(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for action in accepted_or_auto_actions(
        "innovation_rework", "innovation", evaluator_path, decisions_path
    ):
        cluster_id = str(action.get("cluster_id") or action.get("target", ""))
        if cluster_id:
            out[cluster_id] = action
    return out


def innovation_merge_groups(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> list[dict]:
    return accepted_or_auto_actions(
        "innovation_merge", "innovation", evaluator_path, decisions_path
    )
