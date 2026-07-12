import json
import os
import tempfile
import unittest
from pathlib import Path

from agents.gap_analysis_agent import (
    apply_gap_feedback,
    build_topics_block,
    consolidate_clusters,
    validate_and_normalize_gaps,
)


class GapFeedbackTests(unittest.TestCase):
    def test_build_topics_block_uses_real_provenance_aware_topic_removals(self):
        analysis = {
            "llm_interpretation": {
                "relevant_topics": [
                    {"topic_id": str(topic_id), "kernproblem": f"Problem {topic_id}"}
                    for topic_id in range(1, 6)
                ]
            },
            "topic_overview": [
                {"Topic": topic_id, "Name": f"Topic {topic_id}", "Count": topic_id}
                for topic_id in range(1, 6)
            ],
            "topic_sentiments": {},
        }

        def action(action_id, topic_id, autonomy):
            return {
                "action_id": action_id,
                "action_type": "topic_remove",
                "evaluator_run_id": "ER_current",
                "stable_target": f"topic:{topic_id}",
                "target": str(topic_id),
                "topic_id": str(topic_id),
                "target_agent": "gap-analysis",
                "autonomy": autonomy,
            }

        current_human = action("H1", 1, "human_required")
        current_auto = action("A2", 2, "auto_apply")
        rejected_auto = action("A3", 3, "auto_apply")
        deferred_human = action("H4", 4, "human_required")
        stale_human = action("H5", 5, "human_required")

        with tempfile.TemporaryDirectory() as directory:
            original_cwd = Path.cwd()
            try:
                os.chdir(directory)

                # Missing evaluator and human_decisions artifacts are a valid no-feedback case.
                unfiltered = build_topics_block(analysis)
                self.assertIn("--- Topic 1 ---", unfiltered)
                self.assertIn("--- Topic 5 ---", unfiltered)

                evaluation_dir = Path("data/evaluation")
                evaluation_dir.mkdir(parents=True)
                (evaluation_dir / "evaluator_output.json").write_text(
                    json.dumps({
                        "evaluator_run_id": "ER_current",
                        "aktionen": [
                            current_human,
                            current_auto,
                            rejected_auto,
                            deferred_human,
                            stale_human,
                        ],
                    }),
                    encoding="utf-8",
                )
                (evaluation_dir / "human_decisions.json").write_text(
                    json.dumps({
                        "evaluator_run_id": "ER_current",
                        "decisions": [
                            {**current_human, "decision": "accepted"},
                            {**rejected_auto, "decision": "rejected"},
                            {**deferred_human, "decision": "deferred"},
                            {**stale_human, "evaluator_run_id": "ER_old", "decision": "accepted"},
                            {"action_type": "topic_remove", "target": "5", "decision": "accepted"},
                        ],
                    }),
                    encoding="utf-8",
                )

                filtered = build_topics_block(analysis)
            finally:
                os.chdir(original_cwd)

        self.assertNotIn("--- Topic 1 ---", filtered)
        self.assertNotIn("--- Topic 2 ---", filtered)
        self.assertIn("--- Topic 3 ---", filtered)
        self.assertIn("--- Topic 4 ---", filtered)
        self.assertIn("--- Topic 5 ---", filtered)

    def test_prefixed_and_exact_topic_ids_become_canonical(self):
        result = validate_and_normalize_gaps(
            {"gaps": [
                {"topic_id": "1_label_words", "cluster_id": "Leistung Übermittlung Ämter",
                 "klassifizierung": "echte_luecke"},
                {"topic_id": "2", "cluster_id": "zweiter_cluster",
                 "klassifizierung": "echte_luecke"},
            ]},
            {"services": []},
            {"1", "2"},
        )

        first, second = result["gaps"]
        self.assertEqual(first["topic_id"], "1")
        self.assertEqual(second["topic_id"], "2")
        self.assertEqual(first["cluster_id_llm"], "leistung_uebermittlung_aemter")
        self.assertNotIn("unerwartete_topic_id", first["review_reason"])
        self.assertNotIn("unerwartete_topic_id", second["review_reason"])

    def test_multiple_prefixed_gaps_keep_distinct_canonical_ids(self):
        result = validate_and_normalize_gaps(
            {"gaps": [
                {"topic_id": "1_aktenauskunft_unterstützung_behörde_gesetzlich",
                 "klassifizierung": "echte_luecke"},
                {"topic_id": "2_antrag bearbeiten_übermitteln_anwalt_einreichen",
                 "klassifizierung": "echte_luecke"},
                {"topic_id": "5_kümmern_weinen_kennenlernen_mutter",
                 "klassifizierung": "echte_luecke"},
            ]},
            {"services": []},
            {"1", "2", "5"},
        )

        self.assertEqual([gap["topic_id"] for gap in result["gaps"]], ["1", "2", "5"])
        self.assertEqual(
            [gap["cluster_id_llm"] for gap in result["gaps"]],
            [
                "1_aktenauskunft_unterstuetzung_behoerde_gesetzlich",
                "2_antrag_bearbeiten_uebermitteln_anwalt_einreichen",
                "5_kuemmern_weinen_kennenlernen_mutter",
            ],
        )

    def test_unknown_and_ambiguous_topic_prefixes_are_not_guessed(self):
        result = validate_and_normalize_gaps(
            {"gaps": [
                {"topic_id": "99_unknown", "klassifizierung": "echte_luecke"},
                {"topic_id": "1_label_words", "klassifizierung": "echte_luecke"},
            ]},
            {"services": []},
            {"1", "1_label", "2"},
        )

        unknown, ambiguous = result["gaps"]
        self.assertEqual(unknown["topic_id"], "99_unknown")
        self.assertIn("unerwartete_topic_id", unknown["review_reason"])
        self.assertEqual(ambiguous["topic_id"], "1_label_words")
        self.assertIn("unerwartete_topic_id", ambiguous["review_reason"])
        self.assertIn("mehrdeutige_topic_id", ambiguous["review_reason"])

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
