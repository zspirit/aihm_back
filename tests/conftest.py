import hashlib
import os

import pytest
import pytest_asyncio


# ------------------------------------------------------------------
# FAST BCRYPT MOCK — must be installed BEFORE app imports anything
# that calls hash_password at module load time.
# Real bcrypt with cost=12 takes ~250ms per hash; this takes microseconds.
# ------------------------------------------------------------------
def _fast_hashpw(password: bytes, salt: bytes) -> bytes:
    return b"$test$" + hashlib.sha256(password).hexdigest().encode()


def _fast_checkpw(password: bytes, hashed: bytes) -> bool:
    expected = b"$test$" + hashlib.sha256(password).hexdigest().encode()
    return hashed == expected


def _fast_gensalt(rounds: int = 12, prefix: bytes = b"2b") -> bytes:
    return b"$2b$04$" + b"a" * 22


import bcrypt as _bcrypt  # noqa: E402

_bcrypt.hashpw = _fast_hashpw
_bcrypt.checkpw = _fast_checkpw
_bcrypt.gensalt = _fast_gensalt

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402

# PostgreSQL required for integration tests (Docker must be running)
_BASE_TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://aihm:aihm@localhost:5432/aihm_test",
)


def _per_worker_db_url(base_url: str) -> str:
    """Append the xdist worker id to the DB name so each worker gets its own DB.

    Single-process runs use PYTEST_XDIST_WORKER='master' (or unset) → no suffix.
    Parallel runs (-n auto) get gw0, gw1, ... and we suffix accordingly.
    """
    worker = os.getenv("PYTEST_XDIST_WORKER", "")
    if not worker or worker == "master":
        return base_url
    # postgresql+asyncpg://user:pwd@host:port/dbname  →  …/dbname_gw0
    if "/" in base_url:
        head, _, dbname = base_url.rpartition("/")
        return f"{head}/{dbname}_{worker}"
    return base_url


TEST_DATABASE_URL = _per_worker_db_url(_BASE_TEST_DB_URL)

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

# Sync engine/session for tests that call Celery workers directly (process_cv, etc.)
_sync_test_url = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
test_sync_engine = create_engine(_sync_test_url, echo=False, poolclass=NullPool)
TestSyncSession = sessionmaker(test_sync_engine, class_=Session, expire_on_commit=False)


def _ensure_worker_db_exists() -> None:
    """If running under pytest-xdist, the per-worker DB may not exist yet.

    Connect to the default 'postgres' DB and CREATE DATABASE if needed.
    Sync, called once per worker before any async fixture runs.
    """
    worker = os.getenv("PYTEST_XDIST_WORKER", "")
    if not worker or worker == "master":
        return  # baseline DB (aihm_test) is created out-of-band

    import re
    from sqlalchemy import create_engine as _create_sync_engine

    sync_url = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    head, _, target_db = sync_url.rpartition("/")
    admin_url = f"{head}/postgres"

    admin_engine = _create_sync_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target_db}
        ).scalar()
        if not existing:
            # CREATE DATABASE doesn't accept parameters → identifier must be safe.
            safe = re.sub(r"[^A-Za-z0-9_]", "", target_db)
            conn.execute(text(f"CREATE DATABASE {safe}"))
    admin_engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def _create_tables():
    """Create all tables once per test session. Skips only if PostgreSQL is unreachable."""
    try:
        _ensure_worker_db_exists()
    except (ConnectionRefusedError, OSError) as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            pytest.skip(f"PostgreSQL not available: {e}")
        raise

    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except (ConnectionRefusedError, OSError) as e:
        pytest.skip(f"PostgreSQL not available: {e}")
    except Exception as e:
        if "connect" in str(e).lower() or "refused" in str(e).lower():
            pytest.skip(f"PostgreSQL not available: {e}")
        raise
    yield
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except Exception:
        pass


@pytest_asyncio.fixture()
async def _setup_db(_create_tables):
    """Truncate all tables between tests for fast isolation."""
    yield
    async with test_engine.begin() as conn:
        table_names = [t.name for t in reversed(Base.metadata.sorted_tables)]
        if table_names:
            await conn.execute(text(f"TRUNCATE {', '.join(table_names)} CASCADE"))


@pytest_asyncio.fixture()
async def db_session(_setup_db):
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture()
async def client(_setup_db):
    async def override_get_db():
        async with TestSession() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """Disable slowapi rate limiting in tests."""
    from app.core.rate_limit import limiter
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _mock_celery_tasks():
    """Globally mock all Celery task.delay() to prevent Redis connection in tests."""
    from unittest.mock import MagicMock, patch

    tasks = [
        "app.workers.cv_processing.process_cv.delay",
        "app.workers.matching.compute_match_matrix.delay",
        "app.workers.bulk_import.process_bulk_cv_import.delay",
        "app.workers.bulk_import.process_csv_import.delay",
        "app.workers.notifications.send_consent_email.delay",
        "app.workers.notifications.send_consent_reminder.delay",
        "app.workers.notifications.send_email.delay",
        "app.workers.question_generation.generate_questions.delay",
        "app.workers.telephony.initiate_call.delay",
        "app.workers.report_generation.generate_report.delay",
        "app.workers.transcription.transcribe.delay",
        "app.workers.analysis.analyze.delay",
        "app.workers.purge.purge_expired_data.delay",
        "app.workers.feedback.generate_and_send_feedback.delay",
    ]
    patches = []
    for t in tasks:
        try:
            p = patch(t, MagicMock(return_value=None))
            p.start()
            patches.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass
    yield
    for p in patches:
        p.stop()


async def _create_user(db_session, email, role="admin", tenant_name="Test Corp"):
    from app.models.tenant import Tenant
    from app.models.user import User

    tenant = Tenant(name=tenant_name)
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password("testpass123"),
        full_name=f"{role.capitalize()} User",
        role=role,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(
        {
            "sub": str(user.id),
            "tenant_id": str(tenant.id),
            "role": role,
        }
    )
    return {"Authorization": f"Bearer {token}"}, user, tenant


@pytest_asyncio.fixture()
async def auth_headers(db_session):
    headers, _, _ = await _create_user(db_session, "admin@test.com", "admin")
    return headers


@pytest_asyncio.fixture()
async def admin_data(db_session):
    headers, user, tenant = await _create_user(db_session, "admin@test.com", "admin")
    return headers, user, tenant


@pytest_asyncio.fixture()
async def viewer_headers(db_session):
    headers, _, _ = await _create_user(db_session, "viewer@test.com", "viewer", "Viewer Corp")
    return headers


@pytest_asyncio.fixture()
async def test_user(db_session):
    """Create a test user for model tests."""
    from app.models.tenant import Tenant
    from app.models.user import User

    tenant = Tenant(name="Test Tenant")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        email="test@test.com",
        password_hash=hash_password("testpass123"),
        full_name="Test User",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def test_tenant(db_session, test_user):
    """Create a test tenant (uses test_user's tenant)."""
    # Return the tenant from test_user
    from app.models import Tenant
    tenant = await db_session.get(Tenant, test_user.tenant_id)
    return tenant
