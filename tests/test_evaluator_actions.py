import unittest

from agents.evaluator_agent import build_actions


class EvaluatorActionTests(unittest.TestCase):
    def test_build_actions_assigns_autonomy_levels(self):
        output = {
            "topic_evaluations": [
                {
                    "topic_id": "15",
                    "verdict": "remove",
                    "noise": True,
                    "in_scope": False,
                    "begruendung": "Cookie-Artefakt",
                }
            ],
            "gap_evaluations": [
                {
                    "topic_id": "5",
                    "verdict": "reclassify",
                    "vorgeschlagene_klassifikation": "informationsluecke",
                    "begruendung": "Matching fraglich",
                }
            ],
            "innovation_evaluations": [
                {
                    "innovation_id": "INN_001",
                    "begruendung": "Träger prüfen",
                    "rework_briefing": "Träger korrigieren",
                }
            ],
            "aggregierte_aktionen": {
                "regenerieren": ["INN_001"],
                "konvergenz_zusammenfuehren": [["INN_001", "INN_002"]],
            },
            "keyword_feedback": {
                "neue_keywords_vorgeschlagen": ["Kita-Finanzierung"],
                "schwache_keywords": ["ZBFS"],
            },
        }
        inputs = {"source_stats": {
            "reddit": {
                "attempted_requests": 10,
                "blocked_403_count": 10,
                "successful_requests": 0,
                "existing_data_preserved": True,
            }
        }}

        actions = build_actions(output, inputs)
        by_type = {action["action_type"]: action for action in actions}

        self.assertEqual(by_type["topic_remove"]["autonomy"], "auto_apply")
        self.assertEqual(by_type["gap_reclassify"]["autonomy"], "auto_apply")
        self.assertEqual(by_type["innovation_rework"]["autonomy"], "human_required")
        self.assertEqual(by_type["keyword_add"]["autonomy"], "human_required")
        self.assertEqual(by_type["keyword_remove"]["autonomy"], "human_required")
        self.assertEqual(by_type["source_quality_warning"]["autonomy"], "suggestion_only")
        self.assertTrue(all(action["action_id"].startswith("EA_") for action in actions))


if __name__ == "__main__":
    unittest.main()
