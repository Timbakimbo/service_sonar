"""Read-only status and structural validation for the manual pipeline.

This module never starts an agent and never writes pipeline state.  It derives
its result exclusively from the JSON artifacts below ``data/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Artifact:
    path: str
    kind: type
    required_keys: tuple[str, ...] = ()
    non_empty_key: str | None = None


@dataclass(frozen=True)
class Stage:
    name: str
    command: str
    inputs: tuple[Artifact, ...]
    output: Artifact


SOURCES = Artifact("data/raw/sources.json", list)
WEB = Artifact("data/raw/scraped_web.json", list)
REDDIT = Artifact("data/raw/scraped_reddit.json", list)
FRAGDENSTAAT = Artifact("data/raw/scraped_fragdenstaat.json", list)
PREPROCESSED = Artifact("data/preprocessed/preprocessed.json", list)
ANALYSIS = Artifact(
    "data/analysis/analysis_output.json",
    dict,
    ("documents", "topic_overview", "topic_sentiments", "llm_interpretation"),
    "topic_overview",
)
REFERENCE = Artifact(
    "data/reference/existing_services.json", dict, ("schema_version", "services"), "services"
)
GAPS = Artifact(
    "data/gap_analysis/gap_analysis_output_v2.json",
    dict,
    ("schema_version", "gaps", "review_count"),
    "gaps",
)
INNOVATIONS = Artifact(
    "data/innovation/innovation_output.json",
    dict,
    ("schema_version", "innovations", "review_count"),
    "innovations",
)
EVALUATION = Artifact(
    "data/evaluation/evaluator_output.json",
    dict,
    (
        "schema_version",
        "topic_evaluations",
        "gap_evaluations",
        "innovation_evaluations",
        "aggregierte_aktionen",
        "review_count",
        "review_reasons",
    ),
    "topic_evaluations",
)
HUMAN_DECISIONS_PATH = "data/evaluation/human_decisions.json"
METRICS_PATH = "data/metrics.json"

STAGES = (
    Stage("source-discovery", "python -m agents.source_discovery_agent", (), SOURCES),
    Stage("web-scraper", "python -m agents.scraping_agents.webscraping_agent", (SOURCES,), WEB),
    Stage("reddit-scraper", "python -m agents.scraping_agents.reddit_scraper", (), REDDIT),
    Stage("fragdenstaat-scraper", "python -m agents.scraping_agents.fragdenstaat_scraper", (), FRAGDENSTAAT),
    Stage("preprocessing", "python -m agents.preprocessing", (WEB, REDDIT, FRAGDENSTAAT), PREPROCESSED),
    Stage("analysis", "python -m agents.analysis_agent", (PREPROCESSED,), ANALYSIS),
    Stage("gap-analysis", "python -m agents.gap_analysis_agent", (ANALYSIS, REFERENCE), GAPS),
    Stage("innovation", "python -m agents.innovation_agent", (GAPS, REFERENCE), INNOVATIONS),
    Stage("evaluator", "python -m agents.evaluator_agent", (ANALYSIS, GAPS, INNOVATIONS, REFERENCE), EVALUATION),
)


def validate_artifact(root: Path, artifact: Artifact) -> tuple[bool, str]:
    path = root / artifact.path
    if not path.is_file():
        return False, "fehlt"
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"kein gültiges JSON ({exc})"
    if not isinstance(data, artifact.kind):
        return False, f"erwartet {artifact.kind.__name__}, erhalten {type(data).__name__}"
    if isinstance(data, list) and not data:
        return False, "Liste ist leer"
    if isinstance(data, dict):
        missing = [key for key in artifact.required_keys if key not in data]
        if missing:
            return False, "Pflichtfelder fehlen: " + ", ".join(missing)
        if artifact.non_empty_key is not None:
            value = data.get(artifact.non_empty_key)
            if not isinstance(value, (list, dict)) or not value:
                return False, f"Feld {artifact.non_empty_key!r} ist leer oder hat den falschen Typ"
    return True, "valide"


def latest_source_metrics(root: Path, source: str) -> dict[str, Any]:
    path = root / METRICS_PATH
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, list):
        latest: dict[str, Any] = {}
        for item in data:
            if isinstance(item, dict) and item.get("source", "web") == source:
                latest = item
        return latest
    if isinstance(data, dict):
        item = data.get(source, {})
        return item if isinstance(item, dict) else {}
    return {}


def reddit_quality_status(root: Path) -> tuple[str | None, str | None]:
    metrics = latest_source_metrics(root, "reddit")
    if not metrics:
        return None, None
    attempted = int(metrics.get("attempted_requests") or 0)
    blocked = int(metrics.get("blocked_403_count") or 0)
    successful = int(metrics.get("successful_requests") or 0)
    if metrics.get("blocked_run") or (attempted and (successful == 0 or blocked / attempted >= 0.8)):
        return "OUTPUT VALID / BLOCKED", (
            f"letzter Reddit-Run blockiert/stale "
            f"({blocked}/{attempted} 403, successful={successful}, "
            f"existing_preserved={bool(metrics.get('existing_data_preserved'))})"
        )
    if metrics.get("existing_data_preserved") and not metrics.get("fresh_data_collected", True):
        return "OUTPUT VALID / STALE", "bestehender Reddit-Corpus wurde wiederverwendet"
    return None, None


def stage_status(root: Path, stage: Stage) -> tuple[str, str]:
    output_ok, output_detail = validate_artifact(root, stage.output)
    if (root / stage.output.path).exists():
        if output_ok and stage.name == "reddit-scraper":
            quality_status, quality_detail = reddit_quality_status(root)
            if quality_status:
                return quality_status, quality_detail or output_detail
        return ("OUTPUT VALID", output_detail) if output_ok else ("OUTPUT INVALID", output_detail)

    bad_inputs = []
    for artifact in stage.inputs:
        valid, detail = validate_artifact(root, artifact)
        if not valid:
            bad_inputs.append(f"{artifact.path}: {detail}")
    if bad_inputs:
        return "BLOCKED", "; ".join(bad_inputs)
    return "READY", "alle Inputs valide"


def evaluator_action_status(root: Path) -> dict[str, Any]:
    valid, _ = validate_artifact(root, EVALUATION)
    if not valid:
        return {
            "unresolved_human_required": 0, "auto_actions_available": 0,
            "suggestions_available": 0, "stale_decisions_ignored": 0,
            "legacy_human_action_count": 0, "legacy_evaluator_output": False,
            "legacy_auto_action_count": 0, "legacy_suggestion_count": 0,
            "fresh_evaluator_run_required": False,
        }
    with (root / EVALUATION.path).open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    actions = data.get("aktionen", []) if isinstance(data.get("aktionen"), list) else []
    run_id = str(data.get("evaluator_run_id", ""))
    required = {"action_id", "action_type", "evaluator_run_id", "stable_target"}
    provenance_valid = bool(run_id) and all(
        isinstance(action, dict)
        and all(str(action.get(field, "")).strip() for field in required)
        and str(action.get("evaluator_run_id")) == run_id
        for action in actions
    )
    current = {
        str(action.get("action_id")): action
        for action in actions if action.get("action_id")
    }
    decided: set[str] = set()
    stale_count = 0
    decisions_path = root / HUMAN_DECISIONS_PATH
    if decisions_path.is_file():
        try:
            with decisions_path.open(encoding="utf-8") as handle:
                human_data = json.load(handle)
            human_decisions = human_data.get("decisions", [])
            if not provenance_valid:
                stale_count = len(human_decisions)
            for item in human_decisions if provenance_valid else []:
                action_id = str(item.get("action_id", ""))
                action = current.get(action_id)
                matches = (
                    bool(run_id) and str(item.get("evaluator_run_id", "")) == run_id
                    and action is not None
                    and str(item.get("stable_target", "")) == str(action.get("stable_target", ""))
                    and str(item.get("action_type", "")) == str(action.get("action_type", ""))
                )
                if matches and item.get("decision") in ("accepted", "rejected"):
                    decided.add(action_id)
                else:
                    stale_count += 1
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    legacy_human_count = sum(
        1 for action in actions if action.get("autonomy") == "human_required"
    ) if not provenance_valid else 0
    legacy_auto_count = sum(
        1 for action in actions if action.get("autonomy") == "auto_apply"
    ) if not provenance_valid else 0
    legacy_suggestion_count = sum(
        1 for action in actions if action.get("autonomy") == "suggestion_only"
    ) if not provenance_valid else 0
    unresolved = sum(
        1 for action in actions
        if provenance_valid and action.get("autonomy") == "human_required"
        and str(action.get("action_id", "")) not in decided
    )
    return {
        "unresolved_human_required": unresolved,
        "auto_actions_available": sum(
            1 for action in actions if provenance_valid and action.get("autonomy") == "auto_apply"
        ),
        "suggestions_available": sum(
            1 for action in actions if provenance_valid and action.get("autonomy") == "suggestion_only"
        ),
        "stale_decisions_ignored": stale_count,
        "legacy_human_action_count": legacy_human_count,
        "legacy_auto_action_count": legacy_auto_count,
        "legacy_suggestion_count": legacy_suggestion_count,
        "legacy_evaluator_output": not provenance_valid,
        "fresh_evaluator_run_required": not provenance_valid,
    }


def evaluator_gate(root: Path, status: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    status = status or evaluator_action_status(root)
    count = status["unresolved_human_required"]
    return (bool(count), [f"human_required_actions: {count}"] if count else [])


def configure_windows_safe_output() -> None:
    """Avoid UnicodeEncodeError on restrictive Windows console encodings."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def run(root: Path, selected_stage: str | None = None, as_json: bool = False) -> int:
    stages = [stage for stage in STAGES if selected_stage in (None, stage.name)]
    results = []
    for stage in stages:
        status, detail = stage_status(root, stage)
        results.append({"stage": stage.name, "status": status, "detail": detail, "command": stage.command})

    action_status = evaluator_action_status(root)
    human_gate, gate_reasons = evaluator_gate(root, action_status)
    if as_json:
        print(json.dumps({"stages": results, "human_gate": human_gate, "gate_reasons": gate_reasons,
                          "legacy_evaluator_output": action_status["legacy_evaluator_output"],
                          "fresh_evaluator_run_required": action_status["fresh_evaluator_run_required"],
                          "action_status": action_status},
                         ensure_ascii=False, indent=2))
    else:
        width = max(len(item["stage"]) for item in results)
        for item in results:
            print(f"{item['stage']:<{width}}  {item['status']:<14}  {item['detail']}")
        print(
            "\nEvaluator-Aktionen: "
            f"human_offen={action_status['unresolved_human_required']}, "
            f"auto_verfuegbar={action_status['auto_actions_available']}, "
            f"vorschlaege={action_status['suggestions_available']}, "
            f"stale_ignoriert={action_status['stale_decisions_ignored']}, "
            f"legacy_human={action_status['legacy_human_action_count']}, "
            f"legacy_auto={action_status['legacy_auto_action_count']}, "
            f"legacy_vorschlaege={action_status['legacy_suggestion_count']}"
        )
        actionable = next((item for item in results if item["status"] in ("OUTPUT INVALID", "READY")), None)
        if action_status["legacy_evaluator_output"] and selected_stage in (None, "evaluator"):
            print("\nLEGACY EVALUATOR OUTPUT - FRESH EVALUATOR RUN REQUIRED")
            print("Vor Human Review zuerst den Evaluator manuell neu ausfuehren.")
        elif actionable:
            print(f"\nNächste manuelle Aktion: {actionable['command']}")
        elif human_gate and selected_stage in (None, "evaluator"):
            print("\nHUMAN DECISION REQUIRED: " + "; ".join(gate_reasons))
            print("Vorgehen: evaluator_output.json pruefen und den Human-in-the-Loop-Abschnitt im RUNBOOK lesen.")
        elif all(item["status"].startswith("OUTPUT VALID") for item in results):
            print("\nAlle geprüften Stage-Outputs sind technisch valide.")

    return 0 if all(item["status"].startswith("OUTPUT VALID") for item in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Status der manuellen Pipeline anzeigen und JSON-Artefakte prüfen.")
    parser.add_argument("--stage", choices=[stage.name for stage in STAGES])
    parser.add_argument("--json", action="store_true", help="Maschinenlesbare Ausgabe")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.json:
        configure_windows_safe_output()
    return run(args.root.resolve(), args.stage, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
