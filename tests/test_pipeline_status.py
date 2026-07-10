import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.pipeline_status import EVALUATION, REDDIT, SOURCES, evaluator_gate, run, validate_artifact


def write_json(root: Path, relative_path: str, value) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class ArtifactValidationTests(unittest.TestCase):
    def test_missing_artifact_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            valid, detail = validate_artifact(Path(directory), SOURCES)
        self.assertFalse(valid)
        self.assertEqual(detail, "fehlt")

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / SOURCES.path
            path.parent.mkdir(parents=True)
            path.write_text("{", encoding="utf-8")
            valid, detail = validate_artifact(root, SOURCES)
        self.assertFalse(valid)
        self.assertIn("kein gültiges JSON", detail)

    def test_empty_list_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, SOURCES.path, [])
            valid, detail = validate_artifact(root, SOURCES)
        self.assertFalse(valid)
        self.assertEqual(detail, "Liste ist leer")

    def test_non_empty_list_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, SOURCES.path, [{"url": "https://example.test"}])
            self.assertEqual(validate_artifact(root, SOURCES), (True, "valide"))


class PipelineStatusTests(unittest.TestCase):
    def test_source_discovery_is_ready_without_output(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            exit_code = run(Path(directory), "source-discovery")
        self.assertEqual(exit_code, 1)
        self.assertIn("READY", output.getvalue())
        self.assertIn("python -m agents.source_discovery_agent", output.getvalue())

    def test_evaluator_actions_activate_human_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema_version": "1.0-de",
                "topic_evaluations": [{"topic_id": "1"}],
                "gap_evaluations": [],
                "innovation_evaluations": [],
                "aggregierte_aktionen": {"regenerieren": ["INN_001"]},
                "keyword_feedback": {"neue_keywords_vorgeschlagen": ["Elternberatung"]},
                "review_count": 1,
                "review_reasons": ["example"],
            }
            write_json(root, EVALUATION.path, payload)
            active, reasons = evaluator_gate(root)
        self.assertTrue(active)
        self.assertIn("1 Review-Fall/Fälle", reasons)
        self.assertIn("regenerieren: 1", reasons)
        self.assertIn("neue_keywords_vorgeschlagen: 1", reasons)

    def test_evaluator_without_actions_has_no_human_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema_version": "1.0-de",
                "topic_evaluations": [{"topic_id": "1"}],
                "gap_evaluations": [],
                "innovation_evaluations": [],
                "aggregierte_aktionen": {},
                "review_count": 0,
                "review_reasons": [],
            }
            write_json(root, EVALUATION.path, payload)
            self.assertEqual(evaluator_gate(root), (False, []))

    def test_accepted_human_decision_closes_matching_gate_item(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = {
                "schema_version": "1.0-de",
                "topic_evaluations": [{"topic_id": "1"}],
                "gap_evaluations": [],
                "innovation_evaluations": [],
                "aggregierte_aktionen": {"regenerieren": ["INN_001"]},
                "keyword_feedback": {},
                "review_count": 0,
                "review_reasons": [],
            }
            decisions = {"decisions": [{
                "action_type": "innovation_rework", "target": "INN_001", "decision": "accepted"
            }]}
            write_json(root, EVALUATION.path, evaluator)
            write_json(root, "data/evaluation/human_decisions.json", decisions)
            self.assertEqual(evaluator_gate(root), (False, []))

    def test_normalized_actions_report_human_auto_and_suggestion_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = {
                "schema_version": "1.0-de",
                "topic_evaluations": [{"topic_id": "1"}],
                "gap_evaluations": [],
                "innovation_evaluations": [],
                "aggregierte_aktionen": {},
                "review_count": 0,
                "review_reasons": [],
                "aktionen": [
                    {"action_type": "topic_remove", "target": "15", "autonomy": "auto_apply"},
                    {"action_type": "keyword_add", "target": "Kita", "autonomy": "human_required"},
                    {"action_type": "source_quality_warning", "target": "reddit", "autonomy": "suggestion_only"},
                ],
            }
            write_json(root, EVALUATION.path, evaluator)
            active, reasons = evaluator_gate(root)
        self.assertTrue(active)
        self.assertIn("human_required_actions: 1", reasons)
        self.assertIn("auto_apply_actions: 1", reasons)
        self.assertIn("suggestion_only: 1", reasons)

    def test_reddit_blocked_metrics_are_visible_in_status(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            root = Path(directory)
            write_json(root, REDDIT.path, [{"url": "https://reddit.test", "text": "old corpus"}])
            write_json(root, "data/metrics.json", [{
                "source": "reddit",
                "attempted_requests": 10,
                "successful_requests": 0,
                "blocked_403_count": 10,
                "existing_data_preserved": True,
                "blocked_run": True,
            }])
            exit_code = run(root, "reddit-scraper")
        self.assertEqual(exit_code, 0)
        self.assertIn("OUTPUT VALID / BLOCKED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
