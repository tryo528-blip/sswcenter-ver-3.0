from __future__ import annotations

from datetime import date

from app.core.auth import BootstrapInput, bootstrap_installation
from app.core.settings import Environment, assert_safe_test_data_root, get_settings
from app.db.session import build_session_factory, create_postgres_engine


def seed_synthetic() -> None:
    settings = get_settings()
    if settings.environment is not Environment.TEST:
        raise RuntimeError("synthetic seed is allowed only in the test environment")
    if settings.database_url is None or settings.data_root is None:
        raise RuntimeError("synthetic seed requires isolated database and data-root settings")
    if settings.database_name is None or not settings.database_name.endswith(("_test", "_review")):
        raise RuntimeError("synthetic seed refuses non-test PostgreSQL databases")
    assert_safe_test_data_root(settings.data_root)

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as database_session:
            try:
                bootstrap_installation(
                    database_session,
                    BootstrapInput(
                        center_name="합성 테스트 돌봄센터",
                        admin_name="합성 관리자",
                        birth_date=date(1990, 1, 1),
                        sex_code="TEST",
                        start_date=date(2026, 1, 1),
                        pin="100000",
                    ),
                    settings,
                )
                database_session.commit()
            except Exception:
                database_session.rollback()
                raise
    finally:
        engine.dispose()


def main() -> None:
    seed_synthetic()
    print("SYNTHETIC_SEED_OK")


if __name__ == "__main__":
    main()
