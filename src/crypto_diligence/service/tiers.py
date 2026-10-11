"""Service tiers. The paid tier exists in code and stays off until PAID_TIER_ENABLED=true.

Free: three reports per day per email address, public cached reports.
Paid (designed, not switched on): unlimited reports, portfolio watch with alerts, export.
Nothing here takes a payment: the payment step is the one piece not written, on purpose.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..config import Settings


@dataclass(frozen=True)
class Tier:
    name: str
    reports_per_day: int | None  # None means unlimited
    watchlist: bool
    export: bool


FREE = Tier(name="free", reports_per_day=3, watchlist=False, export=False)
PAID = Tier(name="paid", reports_per_day=None, watchlist=True, export=True)


class PaidTierDisabled(Exception):
    """Raised by paid-only features while PAID_TIER_ENABLED is false."""


def email_hash(email: str, salt: str) -> str:
    """Emails are never stored in clear: the quota table keys on this hash."""
    norm = email.strip().lower()
    return hashlib.sha256((salt + ":" + norm).encode("utf-8")).hexdigest()[:32]


def free_tier(settings: Settings) -> Tier:
    return Tier(name="free", reports_per_day=settings.free_reports_per_day, watchlist=False,
                export=False)


def tier_for(email_h: str, settings: Settings, paid_hashes: set[str]) -> Tier:
    """Which tier an email hash gets. Paid membership would come from the payment provider's
    webhook writing into `paid_hashes`; while the tier is off, everyone is free."""
    if settings.paid_tier_enabled and email_h in paid_hashes:
        return PAID
    return free_tier(settings)


def require_paid(settings: Settings, feature: str) -> None:
    if not settings.paid_tier_enabled:
        raise PaidTierDisabled(
            f"{feature} belongs to the paid tier, which is not enabled on this deployment"
        )
