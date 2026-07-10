"""Shared feedback helpers for Evaluator actions and human decisions.

The Evaluator may produce three kinds of actions:
- auto_apply: low-risk corrections consumed by the next manual stage run
- human_required: decisions that must be accepted/rejected/deferred by a human
- suggestion_only: engineering/process suggestions, never applied automatically

This module is intentionally read-only. It never starts stages and never writes
state. JSON artifacts remain the source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EVALUATOR_PATH = Path("data/evaluation/evaluator_output.json")
HUMAN_DECISIONS_PATH = Path("data/evaluation/human_decisions.json")


def load_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def action_key(action: dict) -> tuple[str, str]:
    return str(action.get("action_type", "")), str(action.get("target", ""))


def accepted_human_decisions(decisions_path: Path = HUMAN_DECISIONS_PATH) -> list[dict]:
    data = load_json(decisions_path, {})
    return [
        item for item in data.get("decisions", [])
        if item.get("decision") == "accepted"
    ]


def rejected_human_decision_keys(decisions_path: Path = HUMAN_DECISIONS_PATH) -> set[tuple[str, str]]:
    data = load_json(decisions_path, {})
    return {
        action_key(item)
        for item in data.get("decisions", [])
        if item.get("decision") == "rejected"
    }


def evaluator_actions(evaluator_path: Path = EVALUATOR_PATH) -> list[dict]:
    data = load_json(evaluator_path, {})
    actions = data.get("aktionen", [])
    return actions if isinstance(actions, list) else []


def auto_apply_actions(
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> list[dict]:
    """Return auto_apply Evaluator actions not explicitly rejected by a human."""
    rejected = rejected_human_decision_keys(decisions_path)
    return [
        action for action in evaluator_actions(evaluator_path)
        if action.get("autonomy") == "auto_apply" and action_key(action) not in rejected
    ]


def accepted_or_auto_actions(
    action_type: str | None = None,
    target_agent: str | None = None,
    evaluator_path: Path = EVALUATOR_PATH,
    decisions_path: Path = HUMAN_DECISIONS_PATH,
) -> list[dict]:
    actions = [
        *accepted_human_decisions(decisions_path),
        *auto_apply_actions(evaluator_path, decisions_path),
    ]
    if action_type is not None:
        actions = [a for a in actions if a.get("action_type") == action_type]
    if target_agent is not None:
        actions = [a for a in actions if a.get("target_agent") == target_agent]
    return actions


def topic_removals() -> set[str]:
    return {
        str(action.get("target"))
        for action in accepted_or_auto_actions("topic_remove", "gap-analysis")
    }


def gap_reclassifications() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for action in accepted_or_auto_actions("gap_reclassify", "gap-analysis"):
        topic_id = str(action.get("target", ""))
        proposed = action.get("proposed_value")
        if topic_id and proposed:
            out[topic_id] = action
    return out


def innovation_rework_briefings() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for action in accepted_or_auto_actions("innovation_rework", "innovation"):
        target = str(action.get("target", ""))
        if target:
            out[target] = action
    return out


def innovation_merge_groups() -> list[dict]:
    return accepted_or_auto_actions("innovation_merge", "innovation")
