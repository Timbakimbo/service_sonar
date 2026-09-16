import importlib
import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents import analysis_agent


class AnalysisAgentEncodingAndModelTests(unittest.TestCase):
    def test_source_is_clean_utf8_with_expected_german_text(self):
        source_path = Path(analysis_agent.__file__)
        raw = source_path.read_bytes()
        text = raw.decode("utf-8")

        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        trailing_line_endings = re.search(rb"(?:(?:\r\n)|\r|\n)+\Z", raw)
        self.assertIsNotNone(trailing_line_endings)
        self.assertEqual(
            len(re.findall(rb"(?:\r\n)|\r|\n", trailing_line_endings.group())),
            1,
        )
        for expected in (
            "Kontext für die LLM-Interpretation",
            "Bürokratie bei Anträgen",
            "Impfschäden ohne Familienbezug",
            "Bewerte für jedes Topic ob es RELEVANT",
            "Fasse für relevante Topics das Kernproblem",
            "Markiere irrelevante Topics (z.B. Impfschäden",
            "Sentiment-Analyse läuft",
            "Output gespeichert →",
        ):
            self.assertIn(expected, text)
        for mojibake in ("Г¤", "в†", "Ã", "Â", "�"):
            self.assertNotIn(mojibake, text)

    def test_verified_default_and_environment_override(self):
        self.assertEqual(analysis_agent.DEFAULT_GEMINI_MODEL, "gemini-3.5-flash")

        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_MODEL", None)
                reloaded = importlib.reload(analysis_agent)
                self.assertEqual(reloaded.GEMINI_MODEL, "gemini-3.5-flash")

            with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-test-override"}):
                reloaded = importlib.reload(analysis_agent)
                self.assertEqual(reloaded.GEMINI_MODEL, "gemini-test-override")
        finally:
            importlib.reload(analysis_agent)

    def test_generate_content_receives_selected_model_without_api_call(self):
        calls = []

        class FakeModels:
            @staticmethod
            def generate_content(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    text='{"relevant_topics": [], "irrelevante_topics": []}'
                )

        client = SimpleNamespace(models=FakeModels())
        with patch.object(analysis_agent, "GEMINI_MODEL", "gemini-selected"):
            result = analysis_agent.interpret_topics_with_llm(client, [], {})

        self.assertEqual(result, {"relevant_topics": [], "irrelevante_topics": []})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "gemini-selected")
        self.assertIn("Bürokratie bei Anträgen", calls[0]["contents"])


if __name__ == "__main__":
    unittest.main()
