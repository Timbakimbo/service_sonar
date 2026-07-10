import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from config.keywords import get_effective_keywords
from agents.human_feedback import auto_apply_actions
from agents.scraping_agents.reddit_scraper import SUBREDDITS, init_metrics
from scripts.review_evaluator import collect_actions, review, save_decisions


EVALUATOR = {
    "keyword_feedback": {
        "neue_keywords_vorgeschlagen": ["Kinderbetreuung"],
        "schwache_keywords": ["ZBFS"],
    },
    "aggregierte_aktionen": {
        "regenerieren": ["INN_001"],
        "topics_entfernen": ["3"],
        "reklassifizieren": [],
        "konvergenz_zusammenfuehren": [["INN_001", "INN_002"]],
    },
    "innovation_evaluations": [{"innovation_id": "INN_001", "rework_briefing": "Träger korrigieren"}],
    "topic_evaluations": [{"topic_id": "3", "begruendung": "Out of scope"}],
    "gap_evaluations": [],
}


class HumanReviewTests(unittest.TestCase):
    def test_reddit_metrics_use_runtime_keyword_count(self):
        metrics = init_metrics(["eins", "zwei", "drei"])
        self.assertEqual(metrics["attempted_queries"], 3)
        self.assertEqual(metrics["attempted_subreddits"], len(SUBREDDITS))

    def test_collects_routed_actions(self):
        actions = collect_actions(EVALUATOR)
        self.assertEqual(len(actions), 5)
        self.assertEqual(actions[0]["target_agent"], "source-discovery/reddit-scraper")
        self.assertEqual(actions[2]["recommendation"], "Träger korrigieren")

    def test_collect_actions_defaults_to_human_required_normalized_actions(self):
        evaluator = {"aktionen": [
            {"action_type": "topic_remove", "target": "15", "autonomy": "auto_apply"},
            {"action_type": "keyword_add", "target": "Kita", "autonomy": "human_required"},
            {"action_type": "source_quality_warning", "target": "reddit", "autonomy": "suggestion_only"},
        ]}
        actions = collect_actions(evaluator)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["target"], "Kita")

    def test_collect_actions_can_include_auto_and_suggestions(self):
        evaluator = {"aktionen": [
            {"action_type": "topic_remove", "target": "15", "autonomy": "auto_apply"},
            {"action_type": "keyword_add", "target": "Kita", "autonomy": "human_required"},
            {"action_type": "source_quality_warning", "target": "reddit", "autonomy": "suggestion_only"},
        ]}
        actions = collect_actions(evaluator, include_auto=True, include_suggestions=True)
        self.assertEqual([a["target"] for a in actions], ["15", "Kita", "reddit"])

    def test_auto_apply_actions_skip_human_rejected_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator_path = root / "evaluator.json"
            decisions_path = root / "human_decisions.json"
            evaluator_path.write_text(json.dumps({"aktionen": [
                {"action_type": "topic_remove", "target": "15", "autonomy": "auto_apply"},
                {"action_type": "topic_remove", "target": "22", "autonomy": "auto_apply"},
            ]}), encoding="utf-8")
            decisions_path.write_text(json.dumps({"decisions": [
                {"action_type": "topic_remove", "target": "15", "decision": "rejected"}
            ]}), encoding="utf-8")
            actions = auto_apply_actions(evaluator_path, decisions_path)
        self.assertEqual([action["target"] for action in actions], ["22"])

    def test_review_records_accept_reject_and_defer(self):
        answers = iter(["y", "", "n", "zu allgemein", "s", "", "y", "", "n", ""])
        with redirect_stdout(StringIO()):
            decisions = review(EVALUATOR, "all", lambda _: next(answers))
        self.assertEqual([item["decision"] for item in decisions],
                         ["accepted", "rejected", "deferred", "accepted", "rejected"])
        self.assertEqual(decisions[1]["human_note"], "zu allgemein")

    def test_accepted_keyword_decisions_change_effective_keywords(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "human_decisions.json"
            decisions = [
                {"action_type": "keyword_add", "target": "Kinderbetreuung", "decision": "accepted"},
                {"action_type": "keyword_remove", "target": "ZBFS", "decision": "accepted"},
                {"action_type": "keyword_add", "target": "Nicht übernehmen", "decision": "rejected"},
            ]
            save_decisions(path, Path("evaluator.json"), "keywords", decisions)
            effective = get_effective_keywords(path)
        self.assertIn("Kinderbetreuung", effective)
        self.assertNotIn("ZBFS", effective)
        self.assertNotIn("Nicht übernehmen", effective)

    def test_saved_file_contains_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            decisions = [{"decision": "deferred"}]
            save_decisions(path, Path("evaluator.json"), "all", decisions)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["deferred"], 1)

    def test_later_review_section_preserves_existing_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.json"
            save_decisions(path, Path("evaluator.json"), "keywords", [
                {"action_type": "keyword_add", "target": "Kita", "decision": "accepted"}
            ])
            save_decisions(path, Path("evaluator.json"), "topics", [
                {"action_type": "topic_remove", "target": "3", "decision": "rejected"}
            ])
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["decisions"]), 2)
        self.assertEqual(payload["reviewed_sections"], ["keywords", "topics"])


if __name__ == "__main__":
    unittest.main()
