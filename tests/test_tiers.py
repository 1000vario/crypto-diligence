import pytest

from crypto_diligence.config import Settings
from crypto_diligence.service import tiers


def test_email_hash_is_stable_and_never_the_email():
    a = tiers.email_hash("Someone@Example.org ", "salt")
    assert a == tiers.email_hash("someone@example.org", "salt")
    assert len(a) == 32 and "example" not in a
    assert a != tiers.email_hash("someone@example.org", "other-salt")


def test_everyone_is_free_while_the_paid_tier_is_off():
    settings = Settings(free_reports_per_day=3, paid_tier_enabled=False)
    h = tiers.email_hash("a@b.co", settings.email_salt)
    assert tiers.tier_for(h, settings, {h}).name == "free"
    assert tiers.tier_for(h, settings, {h}).reports_per_day == 3
    with pytest.raises(tiers.PaidTierDisabled):
        tiers.require_paid(settings, "export")


def test_paid_tier_when_switched_on():
    settings = Settings(paid_tier_enabled=True)
    h = tiers.email_hash("a@b.co", settings.email_salt)
    assert tiers.tier_for(h, settings, {h}) == tiers.PAID
    assert tiers.tier_for("other", settings, {h}).name == "free"
    tiers.require_paid(settings, "export")  # no exception
