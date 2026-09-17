import uuid

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import DbDep, UserDep
from app.core.config import get_settings
from app.models import Document, DocumentStatus, User
from app.schemas.document import DocumentOut
from app.services import storage

settings = get_settings()

router = APIRouter(prefix="/documents", tags=["documents"])


def _get_file_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in settings.allowed_extension_list:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed: {', '.join(settings.allowed_extension_list)}",
        )
    return ext


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    user: UserDep,
    db: DbDep,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> Document:
    if file.filename is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing filename")

    file_type = _get_file_type(file.filename)
    document_id = uuid.uuid4()

    try:
        path, sha256, size = storage.save_upload(user.id, document_id, file.filename, file.file)
    except storage.UploadTooLarge:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_size_mb} MB limit",
        )

    document = Document(
        id=document_id,
        user_id=user.id,
        original_filename=storage.safe_filename(file.filename),
        storage_path=str(path),
        file_type=file_type,
        size_bytes=size,
        sha256=sha256,
        status=DocumentStatus.pending,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    from app.ingestion.pipeline import process_document

    background_tasks.add_task(process_document, document_id)

    return document


@router.get("", response_model=list[DocumentOut])
async def list_documents(user: UserDep, db: DbDep) -> list[Document]:
    result = await db.scalars(
        select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    )
    return list(result)


async def _get_owned_document(db, user: User, document_id: uuid.UUID) -> Document:
    document = await db.get(Document, document_id)
    # 404 (not 403) avoids leaking document existence across users.
    if document is None or document.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, user: UserDep, db: DbDep) -> Document:
    return await _get_owned_document(db, user, document_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, user: UserDep, db: DbDep) -> None:
    document = await _get_owned_document(db, user, document_id)

    # Best effort: remove vectors even if DB deletion fails afterwards.
    from app.vectorstore.qdrant_repo import delete_document_points

    await delete_document_points(user.id, document_id)

    await db.delete(document)
    await db.commit()

    storage.delete_document_files(user.id, document_id)
