"""Seed the one official-card fixture owned by the W2 browser harness."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.settings import Environment, get_settings
from app.db.models import Recipient, Staff, UserAccount
from app.db.seed_w0_w2_workflow_test_data import SEED_MARKER
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.w2.policies import plan_notice_source
from app.domains.w2.service import W2Service

CARD_OCCURRENCE_KEY = "w2-browser-e2e-plan-notice"
CARD_RENEWAL_KEY = "w2-browser-e2e-recipient-renewal"
CARD_DUE_DATE = date(2026, 8, 20)
WRITING_DEADLINE = date(2026, 10, 4)


def _marked(key: str) -> str:
    return f"{SEED_MARKER}|{key}"


def seed_w2_official_card_browser_test() -> dict[str, int | str]:
    settings = get_settings()
    if settings.environment is not Environment.TEST:
        raise RuntimeError("W2 browser seed requires SSWCENTER_ENVIRONMENT=test")
    if settings.database_url is None:
        raise RuntimeError("W2 browser seed requires SSWCENTER_DATABASE_URL")
    url = make_url(settings.database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("W2 browser seed only permits loopback PostgreSQL")
    if not (url.database or "").endswith("_browser_test"):
        raise RuntimeError("W2 browser seed requires a dedicated *_browser_test database")

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            admin = session.scalar(
                select(UserAccount).where(
                    UserAccount.account_code == "ADMIN-001",
                    UserAccount.active.is_(True),
                    UserAccount.role_code == "ADMIN",
                )
            )
            recipient = session.scalar(
                select(Recipient).where(Recipient.memo == _marked("R_ACTIVE_HOME_CARE"))
            )
            initial_staff = session.scalar(select(Staff).where(Staff.memo == _marked("SW_ACTIVE")))
            candidate_staff = session.scalar(
                select(Staff).where(Staff.memo == _marked("NU_ACTIVE"))
            )
            if any(item is None for item in (admin, recipient, initial_staff, candidate_staff)):
                raise RuntimeError("W2 browser seed requires the complete workflow seed")
            assert admin is not None
            assert recipient is not None
            assert initial_staff is not None
            assert candidate_staff is not None

            card = W2Service(session).record_official_source(
                plan_notice_source(
                    occurrence_key=CARD_OCCURRENCE_KEY,
                    renewal_key=CARD_RENEWAL_KEY,
                    writing_deadline=WRITING_DEADLINE,
                    target_name=recipient.name,
                    detail="급여계획서 갱신 통보 브라우저 검증",
                    recipient_id=recipient.id,
                ),
                actor_account_id=admin.id,
            )
            if card.due_date != CARD_DUE_DATE:
                raise RuntimeError("W2 browser seed produced the wrong due date")
            if card.assignee_staff_id != initial_staff.id:
                raise RuntimeError("W2 browser seed did not use the dated monthly assignee")
            if candidate_staff.id == initial_staff.id:
                raise RuntimeError("W2 browser seed candidate must differ from current assignee")
            return {
                "card_id": card.id,
                "current_staff_id": initial_staff.id,
                "candidate_staff_id": candidate_staff.id,
                "recipient_id": recipient.id,
            }
    finally:
        engine.dispose()


def main() -> None:
    summary = seed_w2_official_card_browser_test()
    rendered = " ".join(f"{key}={value}" for key, value in summary.items())
    print(f"W2_OFFICIAL_CARD_BROWSER_SEED_GREEN {rendered}")


if __name__ == "__main__":
    main()
