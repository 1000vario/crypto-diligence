from pathlib import Path

from crypto_diligence.config import Settings, _bool


def test_paths_are_coerced_whatever_the_caller_passes():
    s = Settings(data_dir="some/dir", pricing_json="p.json")
    assert s.data_dir == Path("some/dir") and (s.data_dir / "cache").name == "cache"
    assert s.pricing_json == Path("p.json")
    assert Settings().pricing_json is None


def test_from_env_defaults_and_flags():
    s = Settings.from_env({"PAID_TIER_ENABLED": "", "CD_DATA_DIR": "d", "CD_PROVIDER": "OpenAI"})
    assert s.paid_tier_enabled is False and s.data_dir == Path("d") and s.provider == "openai"
    assert Settings.from_env({"PAID_TIER_ENABLED": "yes"}).paid_tier_enabled is True
    assert _bool(None, True) is True and _bool("off", True) is False
