"""Read-only status and structural validation for the manual pipeline.

This module never starts an agent and never writes pipeline state.  It derives
its result exclusively from the JSON artifacts below ``data/``.
"""

from __future__ import annotations

import argparse
import json
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


def stage_status(root: Path, stage: Stage) -> tuple[str, str]:
    output_ok, output_detail = validate_artifact(root, stage.output)
    if (root / stage.output.path).exists():
        return ("OUTPUT VALID", output_detail) if output_ok else ("OUTPUT INVALID", output_detail)

    bad_inputs = []
    for artifact in stage.inputs:
        valid, detail = validate_artifact(root, artifact)
        if not valid:
            bad_inputs.append(f"{artifact.path}: {detail}")
    if bad_inputs:
        return "BLOCKED", "; ".join(bad_inputs)
    return "READY", "alle Inputs valide"


def evaluator_gate(root: Path) -> tuple[bool, list[str]]:
    valid, _ = validate_artifact(root, EVALUATION)
    if not valid:
        return False, []
    with (root / EVALUATION.path).open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    decided: set[tuple[str, str]] = set()
    decisions_path = root / HUMAN_DECISIONS_PATH
    if decisions_path.is_file():
        try:
            with decisions_path.open(encoding="utf-8") as handle:
                human_data = json.load(handle)
            decided = {
                (str(item.get("action_type", "")), str(item.get("target", "")))
                for item in human_data.get("decisions", [])
                if item.get("decision") in ("accepted", "rejected")
            }
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    reasons = []
    review_count = data.get("review_count", 0)
    if isinstance(review_count, int) and review_count > 0:
        reasons.append(f"{review_count} Review-Fall/Fälle")
    actions = data.get("aggregierte_aktionen", {})
    action_types = {
        "regenerieren": "innovation_rework",
        "reklassifizieren": "gap_reclassify",
        "topics_entfernen": "topic_remove",
    }
    if isinstance(actions, dict):
        for name, values in actions.items():
            if not values:
                continue
            if name == "konvergenz_zusammenfuehren":
                open_values = [value for index, value in enumerate(values, 1)
                               if ("innovation_merge", f"merge_group_{index}") not in decided]
            else:
                action_type = action_types.get(name, name)
                open_values = [value for value in values if (action_type, str(value)) not in decided]
            if open_values:
                reasons.append(f"{name}: {len(open_values)}")
    keyword_feedback = data.get("keyword_feedback", {})
    if isinstance(keyword_feedback, dict):
        for name in ("schwache_keywords", "neue_keywords_vorgeschlagen"):
            values = keyword_feedback.get(name)
            action_type = "keyword_remove" if name == "schwache_keywords" else "keyword_add"
            open_values = [value for value in (values or []) if (action_type, str(value)) not in decided]
            if open_values:
                reasons.append(f"{name}: {len(open_values)}")
    return bool(reasons), reasons


def run(root: Path, selected_stage: str | None = None, as_json: bool = False) -> int:
    stages = [stage for stage in STAGES if selected_stage in (None, stage.name)]
    results = []
    for stage in stages:
        status, detail = stage_status(root, stage)
        results.append({"stage": stage.name, "status": status, "detail": detail, "command": stage.command})

    human_gate, gate_reasons = evaluator_gate(root)
    if as_json:
        print(json.dumps({"stages": results, "human_gate": human_gate, "gate_reasons": gate_reasons},
                         ensure_ascii=False, indent=2))
    else:
        width = max(len(item["stage"]) for item in results)
        for item in results:
            print(f"{item['stage']:<{width}}  {item['status']:<14}  {item['detail']}")
        actionable = next((item for item in results if item["status"] in ("OUTPUT INVALID", "READY")), None)
        if actionable:
            print(f"\nNächste manuelle Aktion: {actionable['command']}")
        elif human_gate and selected_stage in (None, "evaluator"):
            print("\nHUMAN DECISION REQUIRED: " + "; ".join(gate_reasons))
            print("Vorgehen: evaluator_output.json prüfen und den Human-in-the-Loop-Abschnitt im RUNBOOK lesen.")
        elif all(item["status"] == "OUTPUT VALID" for item in results):
            print("\nAlle geprüften Stage-Outputs sind technisch valide.")

    return 0 if all(item["status"] == "OUTPUT VALID" for item in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Status der manuellen Pipeline anzeigen und JSON-Artefakte prüfen.")
    parser.add_argument("--stage", choices=[stage.name for stage in STAGES])
    parser.add_argument("--json", action="store_true", help="Maschinenlesbare Ausgabe")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    args = parser.parse_args()
    return run(args.root.resolve(), args.stage, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
