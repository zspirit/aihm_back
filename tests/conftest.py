import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app

# PostgreSQL required for integration tests (Docker must be running)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://aihm:aihm@localhost:5432/aihm",
)

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session")
async def _create_tables():
    """Create all tables once per test session. Skips only if PostgreSQL is unreachable."""
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
        # Truncate all tables in one statement (CASCADE handles FK constraints)
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
