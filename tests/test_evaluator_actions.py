import unittest

from agents.evaluator_agent import build_actions, ensure_priorisierung_vollstaendig


class EvaluatorActionTests(unittest.TestCase):
    def make_actions(self, topics=None, gaps=None, input_gaps=None):
        output = {
            "evaluator_run_id": "ER_current",
            "topic_evaluations": topics or [],
            "gap_evaluations": gaps or [],
            "innovation_evaluations": [],
            "aggregierte_aktionen": {"regenerieren": [], "konvergenz_zusammenfuehren": []},
            "keyword_feedback": {},
        }
        return build_actions(output, {"gaps": input_gaps or [], "innovations": [], "source_stats": {}})

    def test_topic_rights_matrix(self):
        actions = self.make_actions(topics=[
            {"topic_id": "1", "verdict": "remove", "noise": True, "in_scope": False},
            {"topic_id": "2", "verdict": "remove", "noise": False, "in_scope": False,
             "unambiguous": True, "confidence": 0.9},
            {"topic_id": "3", "verdict": "remove", "noise": False, "in_scope": False,
             "unambiguous": False, "confidence": 0.99},
            {"topic_id": "4", "verdict": "remove", "noise": False, "in_scope": False,
             "unambiguous": True, "confidence": 0.8},
        ])
        by_topic = {a["topic_id"]: a for a in actions}
        self.assertEqual(by_topic["1"]["autonomy"], "auto_apply")
        self.assertEqual(by_topic["2"]["autonomy"], "auto_apply")
        self.assertEqual(by_topic["3"]["autonomy"], "human_required")
        self.assertEqual(by_topic["4"]["autonomy"], "human_required")
        self.assertIsNone(by_topic["1"]["confidence"])

    def test_gap_rights_matrix(self):
        input_gaps = [
            {"topic_id": "5", "cluster_id": "elterngeld", "klassifizierung": "prozessproblem"},
            {"topic_id": "6", "cluster_id": "kindergeld", "klassifizierung": "prozessproblem"},
            {"topic_id": "7", "cluster_id": "wohnen", "klassifizierung": "prozessproblem"},
        ]
        actions = self.make_actions(gaps=[
            {"topic_id": "5", "verdict": "reclassify", "vorgeschlagene_klassifikation": "informationsluecke",
             "unambiguous": True, "confidence": 0.9},
            {"topic_id": "6", "verdict": "reclassify", "vorgeschlagene_klassifikation": "informationsluecke",
             "unambiguous": False, "confidence": 0.99},
            {"topic_id": "7", "verdict": "reclassify", "vorgeschlagene_klassifikation": "echte_luecke",
             "unambiguous": True, "confidence": 0.99},
        ], input_gaps=input_gaps)
        by_topic = {a["topic_id"]: a for a in actions}
        self.assertEqual(by_topic["5"]["autonomy"], "auto_apply")
        self.assertEqual(by_topic["6"]["autonomy"], "human_required")
        self.assertEqual(by_topic["7"]["autonomy"], "human_required")
        self.assertEqual(by_topic["5"]["original_value"], "prozessproblem")

    def test_new_real_gap_always_creates_human_review_even_when_evaluator_accepts(self):
        actions = self.make_actions(
            gaps=[{"topic_id": "9", "verdict": "accept", "begruendung": "plausibel"}],
            input_gaps=[{"topic_id": "9", "cluster_id": "solo_9", "klassifizierung": "echte_luecke",
                         "begruendung": "keine Leistung"}],
        )
        action = next(a for a in actions if a["action_type"] == "real_gap_review")
        self.assertEqual(action["autonomy"], "human_required")
        self.assertEqual(action["original_value"], "echte_luecke")
        self.assertEqual(action["evaluator_verdict"], "accept")
        self.assertEqual(action["stable_target"], "gap:solo_9:topic:9")
        self.assertNotIn("proposed_value", action)

    def test_innovation_rework_uses_cluster_identity(self):
        output = {
            "evaluator_run_id": "ER_current", "topic_evaluations": [], "gap_evaluations": [],
            "innovation_evaluations": [{"innovation_id": "INN_005", "verdict": "rework"}],
            "aggregierte_aktionen": {"regenerieren": ["INN_005"], "konvergenz_zusammenfuehren": []},
            "keyword_feedback": {},
        }
        actions = build_actions(output, {"gaps": [], "innovations": [
            {"innovation_id": "INN_005", "cluster_id": "wohnen", "titel": "Wohnhilfe"}
        ], "source_stats": {}})
        action = actions[0]
        self.assertEqual(action["target"], "wohnen")
        self.assertEqual(action["stable_target"], "cluster:wohnen")
        self.assertEqual(action["evaluator_run_id"], "ER_current")

    def test_ranking_removes_invalid_and_duplicate_ids_and_resequences(self):
        ranked = ensure_priorisierung_vollstaendig([
            {"rang": 7, "innovation_id": "INN_005"},
            {"rang": 8, "innovation_id": "INN_005"},
            {"rang": 2, "innovation_id": "INVALID"},
            {"rang": 9, "innovation_id": "INN_001"},
        ], {"INN_001", "INN_005", "INN_007"})
        self.assertEqual([x["innovation_id"] for x in ranked], ["INN_005", "INN_001", "INN_007"])
        self.assertEqual([x["rang"] for x in ranked], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
