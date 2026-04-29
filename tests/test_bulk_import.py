"""
Comprehensive tests for Bulk Import endpoints.

Endpoints covered:
  POST /api/v1/candidates/import-bulk/preview
  POST /api/v1/candidates/import-bulk/{import_id}/confirm
  POST /api/v1/candidates/import-bulk  (legacy)
  GET  /api/v1/imports/recent
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from tests.conftest import _create_user, TestSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_PDF = b"%PDF-1.4 fake pdf content for testing"
FAKE_PDF_2 = b"%PDF-1.4 another fake pdf file content"
FAKE_PDF_3 = b"%PDF-1.4 third fake pdf content stream"

BASE = "/api/v1"
PREVIEW_URL = f"{BASE}/candidates/import-bulk/preview"
CONFIRM_URL_TEMPLATE = f"{BASE}/candidates/import-bulk/{{import_id}}/confirm"
LEGACY_URL = f"{BASE}/candidates/import-bulk"
RECENT_URL = f"{BASE}/imports/recent"


def pdf_file(name: str = "test.pdf", content: bytes = FAKE_PDF):
    return ("files", (name, content, "application/pdf"))


@pytest.fixture()
def mock_s3():
    mock = MagicMock()
    mock.put_object = MagicMock(return_value=None)
    mock.head_bucket = MagicMock(return_value=None)
    with patch("app.services.storage.s3_client", mock), \
         patch("app.services.storage.ensure_bucket", return_value=None), \
         patch("app.services.storage.upload_file", return_value="cvs/test/fake.pdf"):
        yield mock


@pytest.fixture()
def mock_celery_bulk():
    with patch("app.workers.cv_processing.process_cv.delay", MagicMock(return_value=None)), \
         patch("app.workers.bulk_import.process_bulk_cv_import.delay", MagicMock(return_value=None)):
        yield


@pytest_asyncio.fixture()
async def auth_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "admin@test.com", "admin")
    return headers


@pytest_asyncio.fixture()
async def viewer_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "viewer@test.com", "viewer", "Viewer Corp")
    return headers


async def _create_position(client, auth_headers) -> str:
    res = await client.post(
        f"{BASE}/positions",
        headers=auth_headers,
        json={"title": "Dev Backend Python", "required_skills": ["Python"]},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ===========================================================================
# Preview endpoint tests
# ===========================================================================


@pytest.mark.asyncio
async def test_preview_single_pdf(client, auth_headers, mock_s3):
    resp = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Jean_Dupont_CV.pdf")])
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "import_id" in body
    assert body["total_count"] == 1
    assert body["new_count"] == 1
    assert body["duplicate_count"] == 0
    assert len(body["files"]) == 1
    f = body["files"][0]
    assert f["filename"] == "Jean_Dupont_CV.pdf"
    assert f["status"] == "new"
    assert f["candidate_name"] == "Jean Dupont"


@pytest.mark.asyncio
async def test_preview_multiple_files(client, auth_headers, mock_s3):
    files = [
        pdf_file("Alice_Martin.pdf", FAKE_PDF),
        pdf_file("Bob_Leroy.pdf", FAKE_PDF_2),
        pdf_file("Charlie_Nguyen.pdf", FAKE_PDF_3),
    ]
    resp = await client.post(PREVIEW_URL, headers=auth_headers, files=files)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["total_count"] == 3
    assert body["new_count"] == 3
    assert len(body["files"]) == 3


@pytest.mark.asyncio
async def test_preview_with_position(client, auth_headers, mock_s3):
    position_id = await _create_position(client, auth_headers)
    resp = await client.post(
        PREVIEW_URL, headers=auth_headers,
        files=[pdf_file()], data={"position_id": position_id},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["import_id"] is not None


@pytest.mark.asyncio
async def test_preview_without_position(client, auth_headers, mock_s3):
    resp = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Sophie_CV.pdf")])
    assert resp.status_code == 202, resp.text
    assert resp.json()["new_count"] == 1


@pytest.mark.asyncio
async def test_preview_duplicate_detection(client, auth_headers, mock_s3, mock_celery_bulk):
    resp1 = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Karim_CV.pdf", FAKE_PDF)])
    assert resp1.status_code == 202
    import_id1 = resp1.json()["import_id"]
    await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=import_id1), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "import"}]},
    )
    resp2 = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Karim_CV.pdf", FAKE_PDF)])
    assert resp2.status_code == 202
    body2 = resp2.json()
    assert body2["duplicate_count"] == 1
    assert body2["files"][0]["status"] == "duplicate"
    assert body2["files"][0]["duplicate_info"]["match_type"] == "hash"


@pytest.mark.asyncio
async def test_preview_invalid_format(client, auth_headers):
    resp = await client.post(
        PREVIEW_URL, headers=auth_headers,
        files=[("files", ("document.txt", b"plain text", "text/plain"))],
    )
    assert resp.status_code == 400
    assert "Format non supporte" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_preview_too_large(client, auth_headers, mock_s3):
    big_content = b"A" * (10 * 1024 * 1024 + 1)
    resp = await client.post(
        PREVIEW_URL, headers=auth_headers,
        files=[("files", ("big.pdf", big_content, "application/pdf"))],
    )
    assert resp.status_code == 400


# ===========================================================================
# Confirm endpoint tests
# ===========================================================================


@pytest.mark.asyncio
async def test_confirm_import_all(client, auth_headers, mock_s3, mock_celery_bulk):
    resp = await client.post(PREVIEW_URL, headers=auth_headers, files=[
        pdf_file("Anna.pdf", FAKE_PDF), pdf_file("Marc.pdf", FAKE_PDF_2),
    ])
    import_id = resp.json()["import_id"]
    confirm = await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=import_id), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "import"}, {"index": 1, "action": "import"}]},
    )
    assert confirm.status_code == 202
    body = confirm.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0


@pytest.mark.asyncio
async def test_confirm_skip(client, auth_headers, mock_s3, mock_celery_bulk):
    resp = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Skip.pdf")])
    import_id = resp.json()["import_id"]
    confirm = await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=import_id), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "skip"}]},
    )
    assert confirm.status_code == 202
    assert confirm.json()["skipped"] == 1
    assert confirm.json()["imported"] == 0


@pytest.mark.asyncio
async def test_confirm_overwrite(client, auth_headers, mock_s3, mock_celery_bulk):
    # First import
    r1 = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Paul.pdf", FAKE_PDF)])
    await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=r1.json()["import_id"]), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "import"}]},
    )
    # Second preview (duplicate)
    r2 = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Paul.pdf", FAKE_PDF)])
    assert r2.json()["duplicate_count"] == 1
    # Overwrite
    confirm = await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=r2.json()["import_id"]), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "overwrite"}]},
    )
    assert confirm.status_code == 202
    assert confirm.json()["overwritten"] == 1


@pytest.mark.asyncio
async def test_confirm_already_confirmed(client, auth_headers, mock_s3, mock_celery_bulk):
    resp = await client.post(PREVIEW_URL, headers=auth_headers, files=[pdf_file("Lucas.pdf")])
    import_id = resp.json()["import_id"]
    await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=import_id), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "import"}]},
    )
    resp2 = await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=import_id), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "import"}]},
    )
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_confirm_nonexistent(client, auth_headers):
    resp = await client.post(
        CONFIRM_URL_TEMPLATE.format(import_id=str(uuid.uuid4())), headers=auth_headers,
        json={"decisions": [{"index": 0, "action": "import"}]},
    )
    assert resp.status_code == 404


# ===========================================================================
# GET /imports/recent
# ===========================================================================


@pytest.mark.asyncio
async def test_list_recent_imports(client, auth_headers, mock_s3):
    for i in range(2):
        await client.post(PREVIEW_URL, headers=auth_headers,
                          files=[pdf_file(f"C_{i}.pdf", FAKE_PDF if i == 0 else FAKE_PDF_2)])
    resp = await client.get(RECENT_URL, headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 2


@pytest.mark.asyncio
async def test_recent_stuck_cleanup(client, auth_headers):
    from sqlalchemy import select as sa_select
    from app.models.bulk_import import BulkImport
    from app.models.tenant import Tenant
    from app.models.user import User

    # Find tenant/user created by auth_headers fixture
    async with TestSession() as session:
        tenant = (await session.execute(sa_select(Tenant).limit(1))).scalars().first()
        user = (await session.execute(sa_select(User).limit(1))).scalars().first()
        if not tenant or not user:
            pytest.skip("No tenant/user")

        stuck = BulkImport(
            tenant_id=tenant.id, user_id=user.id, filename="stuck.pdf", file_path="bulk",
            total_count=5, processed_count=0, status="pending", source_type="files",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=45),
        )
        session.add(stuck)
        await session.commit()
        stuck_id = str(stuck.id)

    await client.get(RECENT_URL, headers=auth_headers)

    async with TestSession() as session:
        result = await session.execute(sa_select(BulkImport).where(BulkImport.id == uuid.UUID(stuck_id)))
        updated = result.scalar_one_or_none()
        assert updated.status == "failed"


@pytest.mark.asyncio
async def test_recent_time_filter(client, auth_headers):
    from sqlalchemy import select as sa_select
    from app.models.bulk_import import BulkImport
    from app.models.tenant import Tenant
    from app.models.user import User

    async with TestSession() as session:
        tenant = (await session.execute(sa_select(Tenant).limit(1))).scalars().first()
        user = (await session.execute(sa_select(User).limit(1))).scalars().first()
        if not tenant or not user:
            pytest.skip("No tenant/user")

        old = BulkImport(
            tenant_id=tenant.id, user_id=user.id, filename="old.pdf", file_path="bulk",
            total_count=2, processed_count=2, status="completed", source_type="files",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=60),
            completed_at=datetime.now(timezone.utc) - timedelta(minutes=59),
        )
        session.add(old)
        await session.commit()
        old_id = str(old.id)

    resp = await client.get(RECENT_URL, headers=auth_headers)
    returned_ids = [item["id"] for item in resp.json()]
    assert old_id not in returned_ids


# ===========================================================================
# Legacy endpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_legacy_import(client, auth_headers, mock_s3, mock_celery_bulk):
    resp = await client.post(LEGACY_URL, headers=auth_headers, files=[pdf_file("Thomas.pdf")])
    assert resp.status_code == 202
    body = resp.json()
    assert body["total_count"] == 1
    assert body["status"] == "pending"
    assert body["source_type"] == "files"


@pytest.mark.asyncio
async def test_legacy_invalid_format(client, auth_headers):
    resp = await client.post(LEGACY_URL, headers=auth_headers,
                             files=[("files", ("notes.txt", b"text", "text/plain"))])
    assert resp.status_code == 400


# ===========================================================================
# Auth guards
# ===========================================================================


@pytest.mark.asyncio
async def test_preview_requires_auth(client, _setup_db):
    resp = await client.post(PREVIEW_URL, files=[pdf_file()])
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_preview_viewer_forbidden(client, viewer_headers, mock_s3):
    resp = await client.post(PREVIEW_URL, headers=viewer_headers, files=[pdf_file()])
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recent_requires_auth(client, _setup_db):
    resp = await client.get(RECENT_URL)
    assert resp.status_code in (401, 403)
