"""W2 service plan notice pure date helpers.

No DB session, repository, or service layer — date calculation only.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta


def default_end_date(notification_date: date) -> date:
    """Default applied_end_date from notification month.

    Jan–Jun → same-year Dec 31; Jul–Dec → next-year Jun 30.
    """
    if notification_date.month <= 6:
        return date(notification_date.year, 12, 31)
    return date(notification_date.year + 1, 6, 30)


def deadline_date(
    notification_date: date,
    *,
    contract_end_date: date | None = None,
    certification_end_date: date | None = None,
) -> date:
    """Writing deadline: notification_date + 6 months, capped by earlier parent end.

    Month arithmetic clamps day overflow to the last day of the target month
    (e.g. Aug 31 + 6 months → Feb 28/29, never Mar 1–3).
    """
    month = notification_date.month + 6
    year = notification_date.year
    if month > 12:
        month -= 12
        year += 1
    last_day = monthrange(year, month)[1]
    result = date(year, month, min(notification_date.day, last_day))
    caps = [value for value in (contract_end_date, certification_end_date) if value is not None]
    if caps:
        result = min(result, *caps)
    return result


def d45_date(
    notification_date: date,
    *,
    contract_end_date: date | None = None,
    certification_end_date: date | None = None,
) -> date:
    """Deadline minus 45 days (shares cap logic with deadline_date)."""
    return deadline_date(
        notification_date,
        contract_end_date=contract_end_date,
        certification_end_date=certification_end_date,
    ) - timedelta(days=45)
