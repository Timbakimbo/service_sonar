"""Opt-in DuckDuckGo smoke test; normal pytest collection stays offline."""

import os

import pytest
from ddgs import DDGS


@pytest.mark.skipif(
    os.getenv("SERVICE_SONAR_RUN_DDG_SMOKE") != "1",
    reason="network smoke test; set SERVICE_SONAR_RUN_DDG_SMOKE=1 explicitly",
)
def test_ddg_smoke():
    with DDGS() as ddgs:
        results = list(ddgs.text("Elterngeld Bayern Probleme", max_results=5))
    assert results
