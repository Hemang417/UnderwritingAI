import os

# Must happen before any app module is imported: Settings is read (and
# lru_cached) at first import, so the test database has to be in place by
# then, not set later via monkeypatch.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://ic_platform:ic_platform@localhost:5432/ic_platform_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long-for-hs256")

import uuid  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.acquisition.models import DataPointValueType, DataSource, FieldCatalog, SourceType  # noqa: E402
from app.core.db import Base, SessionLocal, engine, get_session  # noqa: E402
from app.discovery.models import CanonicalProject, Developer, RankingConfig  # noqa: E402
from app.identity.models import Permission, Role, role_permissions  # noqa: E402
from app.main import app  # noqa: E402

ROLE_PERMISSIONS = {
    "analyst": ["report.create", "report.edit_draft", "report.submit_review", "datapoint.manual_override"],
    "reviewer": ["report.approve_publish", "report.reject", "datapoint.review_override"],
    "admin": ["user.manage", "adapter.configure", "assumption.configure"],
}

# Mirrors the Alembic seed migration's fixture set (same names/cities/states)
# so integration tests exercise the same exact-match / ambiguous-match /
# city-disambiguation cases the real seed data was designed for.
DISCOVERY_PROJECTS = [
    ("Lodha Group", "Maharashtra", "P51900001234", "Lodha Park", "Worli", "Mumbai", "under_construction"),
    ("Lodha Group", "Maharashtra", "P51900004444", "Lodha Bellissimo", "Mahalaxmi", "Mumbai", "completed"),
    (
        "Godrej Properties",
        "Maharashtra",
        "P52100005678",
        "Godrej Park Avenue",
        "Baner",
        "Pune",
        "under_construction",
    ),
    (
        "Prestige Group",
        "Karnataka",
        "PRM/KA/RERA/1251/2020",
        "Green Valley Residency",
        "Whitefield",
        "Bengaluru",
        "under_construction",
    ),
    (
        "Sobha Ltd",
        "Maharashtra",
        "P52100009999",
        "Green Valley Heights",
        "Hinjewadi",
        "Pune",
        "nearing_completion",
    ),
    ("Oberoi Realty", "Maharashtra", "P51800004321", "Oberoi Springs", "Andheri", "Mumbai", "completed"),
]

DISCOVERY_RANKING_WEIGHTS = {"exact_name": 20, "fuzzy_name": 45, "city": 30, "historical_selection": 5}

# Mirrors the Alembic seed migration for app.acquisition.
ACQUISITION_DATA_SOURCES = [
    ("MahaRERA", SourceType.RERA, "maha_rera", "Maharashtra", 95.0),
    ("Developer Website", SourceType.DEVELOPER_SITE, "developer_site", None, 80.0),
    ("Manual Override", SourceType.MANUAL_OVERRIDE, "manual_override", None, 100.0),
]
# (field_name, value_type, unit, source_priority, staleness_threshold_days, requires_override_review)
ACQUISITION_FIELD_CATALOG = [
    ("unit_count", DataPointValueType.NUMERIC, None, ["rera", "developer_site"], 180, True),
    ("possession_date", DataPointValueType.DATE, None, ["rera", "developer_site"], 365, True),
    (
        "current_price_per_sqft",
        DataPointValueType.NUMERIC,
        "INR/sqft",
        ["developer_site", "rera"],
        30,
        False,
    ),
]


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_database():
    # Drop first: a prior run that crashed mid-teardown (e.g. an event-loop
    # issue) can leave stale tables/seed data behind, which would otherwise
    # make this session's idempotency check below see "already seeded" and
    # skip seeding against what's actually a stale schema.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        # Idempotent: if Alembic migrations already seeded roles/permissions
        # (as happens in CI, which runs `alembic upgrade head` first), don't
        # insert duplicates -- just reuse what's there. Only seed here for a
        # bare `pytest` run against a freshly create_all'd schema.
        already_seeded = (await session.execute(select(Role.name))).scalars().first()

        if not already_seeded:
            roles: dict[str, Role] = {}
            for name in ROLE_PERMISSIONS:
                role = Role(name=name)
                session.add(role)
                roles[name] = role
            await session.flush()

            permission_names = {p for perms in ROLE_PERMISSIONS.values() for p in perms}
            permissions: dict[str, Permission] = {}
            for name in permission_names:
                perm = Permission(name=name)
                session.add(perm)
                permissions[name] = perm
            await session.flush()

            # Insert the join rows directly rather than through the ORM
            # relationship: appending to `role.permissions` here would trigger
            # an implicit lazy-load of the (empty, unloaded) existing
            # collection, which doesn't play well with AsyncSession outside a
            # request-scoped greenlet context.
            await session.execute(
                role_permissions.insert(),
                [
                    {"role_id": roles[role_name].id, "permission_id": permissions[perm_name].id}
                    for role_name, perm_names in ROLE_PERMISSIONS.items()
                    for perm_name in perm_names
                ],
            )

            developers = {name for name, *_ in DISCOVERY_PROJECTS}
            developer_rows = {name: Developer(name=name) for name in developers}
            session.add_all(developer_rows.values())
            await session.flush()

            for developer_name, state, rera, project_name, locality, city, status in DISCOVERY_PROJECTS:
                session.add(
                    CanonicalProject(
                        developer_id=developer_rows[developer_name].id,
                        state=state,
                        rera_registration_number=rera,
                        project_name=project_name,
                        locality=locality,
                        city=city,
                        status=status,
                    )
                )

            session.add(
                RankingConfig(
                    version=1,
                    weights=DISCOVERY_RANKING_WEIGHTS,
                    auto_proceed_threshold=90,
                    show_threshold=40,
                    separation_margin=15,
                    is_active=True,
                )
            )

            for name, source_type, adapter_key, jurisdiction, base_confidence in ACQUISITION_DATA_SOURCES:
                session.add(
                    DataSource(
                        name=name,
                        source_type=source_type,
                        adapter_key=adapter_key,
                        jurisdiction=jurisdiction,
                        base_confidence=base_confidence,
                        is_active=True,
                        legal_review_signed_off=True,
                    )
                )

            for field_entry in ACQUISITION_FIELD_CATALOG:
                field_name, value_type, unit, priority, staleness, requires_review = field_entry
                session.add(
                    FieldCatalog(
                        field_name=field_name,
                        value_type=value_type,
                        unit=unit,
                        source_priority=priority,
                        staleness_threshold_days=staleness,
                        requires_override_review=requires_review,
                    )
                )

            await session.commit()

    yield

    # Defensive: terminate any other lingering backend on this database
    # before dropping tables, so a connection some fixture failed to close
    # cleanly can never wedge this teardown behind a lock wait again.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = current_database() and pid <> pg_backend_pid()"
            )
        )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def _override_get_session():
        # The real get_session dependency wraps its session in `async with`,
        # which rolls back any implicit transaction when the request ends.
        # This override reuses one session across every request in a test,
        # so it has to replicate that per-request rollback explicitly --
        # otherwise each read-only request leaves the shared session
        # "idle in transaction," which then blocks the session-scoped
        # teardown's DROP TABLE behind a lock that never clears.
        try:
            yield db_session
        finally:
            await db_session.rollback()

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"
