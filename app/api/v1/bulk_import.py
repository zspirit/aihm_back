import asyncio
import csv
import io
import json
import uuid as uuid_module
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session, get_db
from app.core.dependencies import get_tenant_id, require_role
from app.models.bulk_import import BulkImport
from app.models.position import Position
from app.models.user import User
from app.schemas.bulk_import import BulkImportDetail, BulkImportResponse
from app.services.storage import upload_file

router = APIRouter(prefix="/positions", tags=["Import"])
settings = get_settings()


@router.post(
    "/{position_id}/candidates/import-csv",
    response_model=BulkImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_csv(
    position_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(
            Position.id == position_id, Position.tenant_id == current_user.tenant_id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Nom de fichier manquant")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("csv", "xlsx", "xls"):
        raise HTTPException(
            status_code=400,
            detail="Format de fichier non supporte. Utiliser .csv, .xlsx ou .xls",
        )

    content = await file.read()
    await file.seek(0)

    # Count rows
    total_count = 0
    if ext == "csv":
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = content.decode("latin-1")
        reader = csv.reader(io.StringIO(text_content))
        rows = list(reader)
        total_count = max(0, len(rows) - 1)  # Exclude header
    elif ext in ("xlsx", "xls"):
        wb = load_workbook(io.BytesIO(content), read_only=True)
        ws = wb.active
        total_count = max(0, ws.max_row - 1)  # Exclude header
        wb.close()

    if total_count > 500:
        raise HTTPException(
            status_code=400, detail="Maximum 500 lignes autorisees par import"
        )

    # Upload file to MinIO
    await file.seek(0)
    file_path = await upload_file(
        file,
        "imports",
        f"{current_user.tenant_id}/{position_id}",
    )

    # Create BulkImport record
    bulk_import = BulkImport(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        position_id=position_id,
        filename=file.filename,
        file_path=file_path,
        total_count=total_count,
        status="pending",
    )
    db.add(bulk_import)
    await db.flush()

    # Trigger worker
    from app.workers.bulk_import import process_csv_import

    process_csv_import.delay(str(bulk_import.id))

    return BulkImportResponse(
        import_id=str(bulk_import.id),
        filename=bulk_import.filename,
        total_count=bulk_import.total_count,
        status=bulk_import.status,
    )


@router.get("/{position_id}/imports/{import_id}/events")
async def import_events(
    position_id: UUID,
    import_id: UUID,
    request: Request,
    tenant_id: UUID = Depends(get_tenant_id),
):
    async def event_stream():
        last_processed = None
        last_status = None
        while True:
            if await request.is_disconnected():
                break
            async with async_session() as db:
                result = await db.execute(
                    select(BulkImport).where(
                        BulkImport.id == import_id,
                        BulkImport.position_id == position_id,
                        BulkImport.tenant_id == tenant_id,
                    )
                )
                bulk_import = result.scalar_one_or_none()
            if not bulk_import:
                yield f"event: error\ndata: {json.dumps({'detail': 'Import introuvable'})}\n\n"
                break
            processed_changed = bulk_import.processed_count != last_processed
            status_changed = bulk_import.status != last_status
            if processed_changed or status_changed:
                last_processed = bulk_import.processed_count
                last_status = bulk_import.status
                data = {
                    "processed": bulk_import.processed_count,
                    "total": bulk_import.total_count,
                    "success": bulk_import.success_count,
                    "errors": bulk_import.error_count,
                    "status": bulk_import.status,
                }
                yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                if bulk_import.status in ("completed", "failed"):
                    yield f"event: done\ndata: {json.dumps({'status': bulk_import.status})}\n\n"
                    break
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{position_id}/imports", response_model=list[BulkImportDetail])
async def list_imports(
    position_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BulkImport)
        .where(BulkImport.position_id == position_id, BulkImport.tenant_id == tenant_id)
        .order_by(BulkImport.created_at.desc())
    )
    imports = result.scalars().all()

    return [
        BulkImportDetail(
            id=str(imp.id),
            filename=imp.filename,
            total_count=imp.total_count,
            processed_count=imp.processed_count,
            success_count=imp.success_count,
            error_count=imp.error_count,
            status=imp.status,
            error_details=imp.error_details,
            created_at=imp.created_at,
            completed_at=imp.completed_at,
        )
        for imp in imports
    ]
