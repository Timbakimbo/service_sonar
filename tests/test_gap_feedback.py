import unittest

from agents.gap_analysis_agent import apply_gap_feedback, consolidate_clusters


class GapFeedbackTests(unittest.TestCase):
    def test_reclassify_with_bad_matching_clears_match_and_forces_solo_cluster(self):
        gaps = [
            {
                "topic_id": "5",
                "klassifizierung": "informationsluecke",
                "matching_services": ["Beratungsstelle Radikalisierung"],
                "review_reason": "",
            },
            {
                "topic_id": "11",
                "klassifizierung": "informationsluecke",
                "matching_services": ["Beratungsstelle Radikalisierung"],
                "review_reason": "",
            },
        ]
        actions = {
            "5": {
                "action_type": "gap_reclassify",
                "target": "5",
                "proposed_value": "prozessproblem",
                "autonomy": "auto_apply",
                "recommendation": "Matching-Dienste passen nicht gut zum Kernproblem.",
                "action_id": "EA_010",
            }
        }

        applied = apply_gap_feedback(gaps, actions)
        consolidate_clusters(gaps)

        self.assertEqual(applied, 1)
        self.assertEqual(gaps[0]["matching_services"], [])
        self.assertEqual(gaps[0]["matching_services_original"], ["Beratungsstelle Radikalisierung"])
        self.assertEqual(gaps[0]["cluster_id"], "solo_5")
        self.assertTrue(gaps[0]["force_solo_cluster"])
        self.assertIn("evaluator_matching_unplausibel", gaps[0]["review_reason"])
        self.assertEqual(gaps[1]["cluster_id"], "solo_11")


if __name__ == "__main__":
    unittest.main()
