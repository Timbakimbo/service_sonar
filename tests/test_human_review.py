import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agents.human_feedback import (
    accepted_human_decisions, auto_apply_actions, innovation_rework_briefings,
)
from agents.scraping_agents.reddit_scraper import SUBREDDITS, init_metrics
from config.keywords import get_effective_keywords
from scripts import review_evaluator as review_module
from scripts.review_evaluator import collect_actions, review, save_decisions, stale_decision_count


def action(action_id, action_type, stable_target, autonomy="human_required", target="target"):
    return {
        "evaluator_run_id": "ER_current", "action_id": action_id,
        "action_type": action_type, "stable_target": stable_target,
        "autonomy": autonomy, "target": target,
        "target_agent": "innovation" if action_type.startswith("innovation") else "gap-analysis",
        "recommendation": "prüfen",
    }


class HumanReviewTests(unittest.TestCase):
    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_reddit_metrics_use_runtime_keyword_count(self):
        metrics = init_metrics(["eins", "zwei", "drei"])
        self.assertEqual(metrics["attempted_queries"], 3)
        self.assertEqual(metrics["attempted_subreddits"], len(SUBREDDITS))

    def test_review_records_accept_reject_and_defer_with_provenance(self):
        evaluator = {"evaluator_run_id": "ER_current", "aktionen": [
            action("A1", "real_gap_review", "gap:g1:topic:1", target="g1"),
            action("A2", "keyword_add", "keyword:kita", target="Kita"),
            action("A3", "innovation_rework", "cluster:wohnen", target="wohnen"),
        ]}
        answers = iter(["y", "fachlich geprüft", "n", "nicht passend", "s", "später"])
        with redirect_stdout(StringIO()):
            decisions = review(evaluator, "all", lambda _: next(answers))
        self.assertEqual([item["decision"] for item in decisions], ["accepted", "rejected", "deferred"])
        self.assertTrue(all(item["evaluator_run_id"] == "ER_current" for item in decisions))
        self.assertEqual(decisions[0]["human_reason"], "fachlich geprüft")

    def test_auto_apply_rejected_and_deferred_are_not_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            actions = [
                action("A1", "topic_remove", "topic:1", "auto_apply", "1"),
                action("A2", "topic_remove", "topic:2", "auto_apply", "2"),
                action("A3", "topic_remove", "topic:3", "auto_apply", "3"),
            ]
            self.write(ep, {"evaluator_run_id": "ER_current", "aktionen": actions})
            self.write(dp, {"evaluator_run_id": "ER_current", "decisions": [
                {**actions[0], "decision": "rejected"}, {**actions[1], "decision": "deferred"},
            ]})
            eligible = auto_apply_actions(ep, dp)
        self.assertEqual([item["target"] for item in eligible], ["3"])

    def test_legacy_auto_apply_action_is_not_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            legacy = action("OLD", "topic_remove", "topic:1", "auto_apply", "1")
            legacy.pop("evaluator_run_id")
            self.write(ep, {"aktionen": [legacy]})
            self.write(dp, {"decisions": []})
            self.assertEqual(auto_apply_actions(ep, dp), [])

    def test_human_decision_cannot_override_authoritative_action_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            current = action("A1", "innovation_rework", "cluster:housing", target="housing")
            current.update({"autonomy": "human_required", "confidence": 0.6, "risk": "medium"})
            malicious = {
                **current, "decision": "accepted", "target": "health",
                "target_agent": "evil-agent", "autonomy": "auto_apply", "confidence": 1.0,
                "risk": "none", "recommendation": "replace current action",
            }
            self.write(ep, {"evaluator_run_id": "ER_current", "aktionen": [current]})
            self.write(dp, {"evaluator_run_id": "ER_current", "decisions": [malicious]})
            combined = accepted_human_decisions(ep, dp)[0]
        for field in ("action_type", "action_id", "evaluator_run_id", "stable_target",
                      "target", "target_agent", "autonomy", "confidence", "risk", "recommendation"):
            self.assertEqual(combined[field], current[field])
        self.assertEqual(combined["decision"], "accepted")

    def test_decision_with_changed_action_type_is_not_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            current = action("A1", "innovation_rework", "cluster:housing", target="housing")
            changed = {**current, "action_type": "keyword_add", "decision": "accepted"}
            self.write(ep, {"evaluator_run_id": "ER_current", "aktionen": [current]})
            self.write(dp, {"evaluator_run_id": "ER_current", "decisions": [changed]})
            self.assertEqual(accepted_human_decisions(ep, dp), [])

    def test_normalized_action_filtering_and_optional_inclusions(self):
        evaluator = {"evaluator_run_id": "ER_current", "aktionen": [
            action("A1", "topic_remove", "topic:1", "auto_apply", "1"),
            action("H1", "keyword_add", "keyword:kita", "human_required", "Kita"),
            action("S1", "source_quality_warning", "source:reddit", "suggestion_only", "reddit"),
        ]}
        self.assertEqual([item["action_id"] for item in collect_actions(evaluator)], ["H1"])
        included = collect_actions(evaluator, include_auto=True, include_suggestions=True)
        self.assertEqual([item["action_id"] for item in included], ["A1", "H1", "S1"])
        self.assertEqual([item["action_id"] for item in collect_actions(evaluator, section="keywords")], ["H1"])

    def test_deferred_action_remains_visible_with_only_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dp = root / "d.json"
            current = action("H1", "innovation_rework", "cluster:housing", target="housing")
            evaluator = {"evaluator_run_id": "ER_current", "aktionen": [current]}
            self.write(dp, {"evaluator_run_id": "ER_current", "decisions": [
                {**current, "decision": "deferred"}
            ]})
            open_actions = collect_actions(evaluator, only_open=True, decisions_path=dp)
        self.assertEqual([item["action_id"] for item in open_actions], ["H1"])

    def test_stale_old_inn_005_decision_cannot_affect_new_inn_005_cluster(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            current = action("EA_innovation_rework_housing", "innovation_rework",
                             "cluster:housing", target="housing")
            current.update({"cluster_id": "housing", "innovation_id": "INN_005"})
            stale = action("EA_innovation_rework_health", "innovation_rework",
                           "cluster:health", target="health")
            stale.update({"evaluator_run_id": "ER_old", "cluster_id": "health",
                          "innovation_id": "INN_005", "decision": "accepted"})
            self.write(ep, {"evaluator_run_id": "ER_current", "aktionen": [current]})
            self.write(dp, {"evaluator_run_id": "ER_old", "decisions": [stale]})
            briefings = innovation_rework_briefings(ep, dp)
        self.assertEqual(briefings, {})

    def test_current_accepted_rework_is_keyed_by_cluster(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            current = action("A1", "innovation_rework", "cluster:housing", target="housing")
            current["cluster_id"] = "housing"
            self.write(ep, {"evaluator_run_id": "ER_current", "aktionen": [current]})
            self.write(dp, {"evaluator_run_id": "ER_current", "decisions": [
                {**current, "decision": "accepted"}
            ]})
            briefings = innovation_rework_briefings(ep, dp)
        self.assertEqual(list(briefings), ["housing"])

    def test_accepted_keywords_require_current_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            add = action("KA", "keyword_add", "keyword:kinderbetreuung", target="Kinderbetreuung")
            add["target_agent"] = "source-discovery/reddit-scraper"
            remove = action("KR", "keyword_remove", "keyword:zbfs", target="ZBFS")
            remove["target_agent"] = "source-discovery/reddit-scraper"
            self.write(ep, {"evaluator_run_id": "ER_current", "aktionen": [add, remove]})
            self.write(dp, {"evaluator_run_id": "ER_current", "decisions": [
                {**add, "decision": "accepted"}, {**remove, "decision": "accepted"},
            ]})
            effective = get_effective_keywords(dp, ep)
        self.assertIn("Kinderbetreuung", effective)
        self.assertNotIn("ZBFS", effective)

    def test_save_decisions_replaces_stale_run_and_keeps_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            evaluator = {"evaluator_run_id": "ER_current", "aktionen": []}
            self.write(ep, evaluator)
            self.write(dp, {"evaluator_run_id": "ER_old", "decisions": [
                {"action_id": "OLD", "decision": "accepted"}
            ]})
            decision = {**action("A1", "keyword_add", "keyword:kita", target="Kita"),
                        "decision": "deferred"}
            save_decisions(dp, ep, "keywords", [decision], evaluator=evaluator)
            payload = json.loads(dp.read_text(encoding="utf-8"))
        self.assertEqual(payload["evaluator_run_id"], "ER_current")
        self.assertEqual([x["action_id"] for x in payload["decisions"]], ["A1"])
        self.assertEqual(payload["summary"]["deferred"], 1)

    def test_repeated_review_sections_merge_for_same_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "e.json"; dp = root / "d.json"
            evaluator = {"evaluator_run_id": "ER_current", "aktionen": []}
            self.write(ep, evaluator)
            save_decisions(dp, ep, "keywords", [
                {**action("K1", "keyword_add", "keyword:kita", target="Kita"), "decision": "accepted"}
            ], evaluator=evaluator)
            save_decisions(dp, ep, "topics", [
                {**action("T1", "topic_remove", "topic:3", target="3"), "decision": "rejected"}
            ], evaluator=evaluator)
            payload = json.loads(dp.read_text(encoding="utf-8"))
        self.assertEqual(payload["reviewed_sections"], ["keywords", "topics"])
        self.assertEqual({item["action_id"] for item in payload["decisions"]}, {"K1", "T1"})

    def test_duplicate_stale_records_are_counted_individually(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); dp = root / "d.json"
            current = action("A1", "keyword_add", "keyword:kita", target="Kita")
            evaluator = {"evaluator_run_id": "ER_current", "aktionen": [current]}
            stale = {**current, "evaluator_run_id": "ER_old", "decision": "accepted"}
            self.write(dp, {"decisions": [stale, dict(stale)]})
            self.assertEqual(stale_decision_count(dp, evaluator), 2)

    def test_legacy_evaluator_refuses_review_before_prompt_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ep = root / "legacy.json"; dp = root / "decisions.json"
            original = b'{"existing":"unchanged"}'; dp.write_bytes(original)
            self.write(ep, {"aktionen": [{"action_type": "keyword_add", "target": "Kita"}]})
            with patch("sys.argv", ["review_evaluator.py", "--input", str(ep), "--output", str(dp)]), \
                 patch.object(review_module, "review") as interactive, redirect_stdout(StringIO()) as output:
                result = review_module.main()
            self.assertEqual(result, 1)
            interactive.assert_not_called()
            self.assertEqual(dp.read_bytes(), original)
            self.assertIn("frischen Evaluator-Lauf", output.getvalue())


if __name__ == "__main__":
    unittest.main()
