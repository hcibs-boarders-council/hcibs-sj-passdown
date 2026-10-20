
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import Claim


SINGAPORE_TZ = ZoneInfo("Asia/Singapore")
DAILY_CLAIM_LIMIT = 2

# These statuses count toward the daily claim limit.
# Completed claims still count.
# Rejected and cancelled claims do not count.
COUNTED_CLAIM_STATUSES = [
    Claim.Status.PENDING,
    Claim.Status.APPROVED,
    Claim.Status.COMPLETED,
]


def singapore_day_bounds():
    """Return the start and end of today's Singapore calendar day."""
    now_singapore = timezone.now().astimezone(SINGAPORE_TZ)

    start = now_singapore.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    end = start + timedelta(days=1)

    return start, end


def active_claim_count_today(user):
    """
    Count today's pending, approved, and completed claims
    using Singapore calendar-day boundaries.
    """
    start, end = singapore_day_bounds()

    return Claim.objects.filter(
        claimant=user,
        status__in=COUNTED_CLAIM_STATUSES,
        created_at__gte=start,
        created_at__lt=end,
    ).count()


def has_daily_claim_capacity(user):
    """Return whether the user can submit another counted claim today."""
    return active_claim_count_today(user) < DAILY_CLAIM_LIMIT
