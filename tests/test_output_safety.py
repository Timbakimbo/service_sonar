import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents import evaluator_agent, innovation_agent


class EvaluatorOutputSafetyTests(unittest.TestCase):
    def inputs(self):
        return {
            "topic_overview": [{"Topic": 1}], "gaps": [], "innovations": [],
            "source_stats_status": "missing", "source_stats": {}, "reference": {"services": []},
            "keywords": [], "relevant_by_id": {}, "irrelevant_by_id": {}, "topic_sentiments": {},
        }

    def test_all_pass_failure_preserves_existing_output_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evaluator.json"; original = b'{"valid":"old"}'
            output.write_bytes(original)
            failing = patch.multiple(
                evaluator_agent,
                run_pass1_topics=lambda _i: (_ for _ in ()).throw(RuntimeError("fail")),
                run_pass2_gaps=lambda *_: (_ for _ in ()).throw(RuntimeError("fail")),
                run_pass3_innovations=lambda *_: (_ for _ in ()).throw(RuntimeError("fail")),
                run_pass4_aggregation=lambda *_: (_ for _ in ()).throw(RuntimeError("fail")),
            )
            with patch.object(evaluator_agent, "OUTPUT_PATH", output), \
                 patch.object(evaluator_agent, "load_evaluator_inputs", return_value=self.inputs()), \
                 patch.object(evaluator_agent, "get_llm_client", return_value=object()), failing:
                result = evaluator_agent.run()
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)

    def test_client_failure_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evaluator.json"; original = b'{"valid":"old"}'
            output.write_bytes(original)
            with patch.object(evaluator_agent, "OUTPUT_PATH", output), \
                 patch.object(evaluator_agent, "load_evaluator_inputs", return_value=self.inputs()), \
                 patch.object(evaluator_agent, "get_llm_client", side_effect=RuntimeError("missing key")):
                result = evaluator_agent.run()
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)

    def test_partial_evaluator_output_records_failed_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evaluator.json"
            with patch.object(evaluator_agent, "OUTPUT_PATH", output), \
                 patch.object(evaluator_agent, "load_evaluator_inputs", return_value=self.inputs()), \
                 patch.object(evaluator_agent, "get_llm_client", return_value=object()), \
                 patch.object(evaluator_agent, "run_pass1_topics", return_value={"topic_evaluations": [
                     {"topic_id": "1", "verdict": "keep", "in_scope": True, "noise": False},
                     {"topic_id": "missing", "verdict": "unknown"},
                 ]}), \
                 patch.object(evaluator_agent, "run_pass2_gaps", side_effect=RuntimeError("p2")), \
                 patch.object(evaluator_agent, "run_pass3_innovations", side_effect=RuntimeError("p3")), \
                 patch.object(evaluator_agent, "run_pass4_aggregation", side_effect=RuntimeError("p4")):
                result = evaluator_agent.run()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["output_status"], "partial")
            self.assertEqual(payload["failed_pass_count"], 3)
            self.assertEqual(len(payload["topic_evaluations"]), 1)

    def test_syntactically_valid_but_unusable_passes_preserve_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evaluator.json"; original = b'{"valid":"old"}'
            output.write_bytes(original)
            with patch.object(evaluator_agent, "OUTPUT_PATH", output), \
                 patch.object(evaluator_agent, "load_evaluator_inputs", return_value=self.inputs()), \
                 patch.object(evaluator_agent, "get_llm_client", return_value=object()), \
                 patch.object(evaluator_agent, "run_pass1_topics", return_value={"topic_evaluations": [{}]}), \
                 patch.object(evaluator_agent, "run_pass2_gaps", return_value={"gap_evaluations": [{}]}), \
                 patch.object(evaluator_agent, "run_pass3_innovations", return_value={"innovation_evaluations": [{}]}), \
                 patch.object(evaluator_agent, "run_pass4_aggregation", return_value={}):
                result = evaluator_agent.run()
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)


class InnovationOutputSafetyTests(unittest.TestCase):
    def write_inputs(self, root, gaps):
        gap_path = root / "gaps.json"; ref_path = root / "reference.json"
        gap_path.write_text(json.dumps({"gaps": gaps}), encoding="utf-8")
        ref_path.write_text(json.dumps({"services": []}), encoding="utf-8")
        return gap_path, ref_path

    def common_patches(self):
        return (
            patch.object(innovation_agent, "report_stale_decisions", return_value=0),
            patch.object(innovation_agent, "innovation_rework_briefings", return_value={}),
            patch.object(innovation_agent, "innovation_merge_groups", return_value=[]),
        )

    def test_all_eligible_cluster_failures_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "innovation.json"; original = b'{"valid":"old"}'
            output.write_bytes(original)
            gp, rp = self.write_inputs(root, [{"topic_id": "1", "cluster_id": "c1",
                                               "klassifizierung": "prozessproblem"}])
            p1, p2, p3 = self.common_patches()
            with patch.object(innovation_agent, "GAP_V2_PATH", gp), patch.object(innovation_agent, "REFERENCE_PATH", rp), \
                 patch.object(innovation_agent, "OUTPUT_PATH", output), \
                 patch.object(innovation_agent, "get_llm_client", return_value=object()), \
                 patch.object(innovation_agent, "run_innovation", side_effect=RuntimeError("api down")), p1, p2, p3:
                result = innovation_agent.run()
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)

    def test_zero_eligible_clusters_is_valid_without_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "innovation.json"
            gp, rp = self.write_inputs(root, [{"topic_id": "1", "cluster_id": "c1",
                                               "klassifizierung": "bereits_abgedeckt"}])
            with patch.object(innovation_agent, "GAP_V2_PATH", gp), patch.object(innovation_agent, "REFERENCE_PATH", rp), \
                 patch.object(innovation_agent, "OUTPUT_PATH", output), \
                 patch.object(innovation_agent, "get_llm_client") as client:
                result = innovation_agent.run()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            client.assert_not_called()
            self.assertEqual(payload["output_status"], "complete_empty_input")

    def test_partial_success_records_failed_cluster_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "innovation.json"
            gp, rp = self.write_inputs(root, [
                {"topic_id": "1", "cluster_id": "c1", "klassifizierung": "prozessproblem"},
                {"topic_id": "2", "cluster_id": "c2", "klassifizierung": "prozessproblem"},
            ])
            raw = {
                "innovation_typ": "digitalisierung", "titel": "Digitaler Familien-Antragsassistent",
                "kurzbeschreibung": "Hilfe", "konkrete_loesung": "Geführter digitaler Prozess.",
                "zielgruppen": ["Familien"], "moegliche_traeger": ["ZBFS"],
                "anknuepfungspunkte": [], "integrationspunkte": [],
                "erwarteter_nutzen": "Weniger Fehler", "umsetzungshuerden": ["Datenschutz"],
                "geschaetzter_aufwand": "mittel", "prioritaet": 3, "confidence": 0.7,
            }
            p1, p2, p3 = self.common_patches()
            with patch.object(innovation_agent, "GAP_V2_PATH", gp), patch.object(innovation_agent, "REFERENCE_PATH", rp), \
                 patch.object(innovation_agent, "OUTPUT_PATH", output), \
                 patch.object(innovation_agent, "get_llm_client", return_value=object()), \
                 patch.object(innovation_agent, "run_innovation", side_effect=[raw, {}]), \
                 p1, p2, p3:
                result = innovation_agent.run()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["output_status"], "partial")
            self.assertEqual(payload["failed_cluster_count"], 1)
            self.assertEqual(payload["failed_clusters"][0]["cluster_id"], "c2")

    def test_all_unusable_innovation_objects_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "innovation.json"; original = b'{"valid":"old"}'
            output.write_bytes(original)
            gp, rp = self.write_inputs(root, [{"topic_id": "1", "cluster_id": "c1",
                                               "klassifizierung": "prozessproblem"}])
            p1, p2, p3 = self.common_patches()
            with patch.object(innovation_agent, "GAP_V2_PATH", gp), patch.object(innovation_agent, "REFERENCE_PATH", rp), \
                 patch.object(innovation_agent, "OUTPUT_PATH", output), \
                 patch.object(innovation_agent, "get_llm_client", return_value=object()), \
                 patch.object(innovation_agent, "run_innovation", return_value={}), p1, p2, p3:
                result = innovation_agent.run()
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
