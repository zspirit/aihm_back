import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app

# PostgreSQL required for integration tests (Docker must be running)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://aihm:aihm@localhost:5432/aihm",
)

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture()
async def _setup_db():
    """Create tables, yield, then drop. Skips if PostgreSQL unavailable."""
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        pytest.skip("PostgreSQL not available (start Docker)")
    yield
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except Exception:
        pass


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
