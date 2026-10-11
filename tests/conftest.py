"""Shared fixtures: settings in a temp dir, HTTP replayed from recorded fixtures, no model."""

from __future__ import annotations

from pathlib import Path

import pytest

from crypto_diligence.config import Settings
from crypto_diligence.tools import fixtures, http
from crypto_diligence.tools.context import ToolContext

FIXTURES = Path(__file__).parent / "fixtures"
HTTP_FIXTURES = FIXTURES / "http"

UNI = "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
EUL = "0xd9Fcd98c322942075A5C3860693e9f4f03AAE07b"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", model_orchestrator="claude-opus-5-5",
                    model_subagent="claude-opus-5-5")


@pytest.fixture
async def ctx(settings: Settings):
    http.configure(fixtures.replay_transport(HTTP_FIXTURES))
    yield ToolContext(settings, resolve_hosts=False)
    await http.aclose()
