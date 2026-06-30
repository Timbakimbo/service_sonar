import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from config.keywords import get_effective_keywords
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
    def test_collects_routed_actions(self):
        actions = collect_actions(EVALUATOR)
        self.assertEqual(len(actions), 5)
        self.assertEqual(actions[0]["target_agent"], "source-discovery/reddit-scraper")
        self.assertEqual(actions[2]["recommendation"], "Träger korrigieren")

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
