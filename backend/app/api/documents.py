import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.storage import build_storage_key, delete_file, generate_download_url, upload_file
from app.db.base import get_db
from app.db.models import Account, Document, DocumentPage, DocumentStatus, User
from app.pipeline.tasks import normalize_document, process_document
from app.schemas.document import DocumentAccountUpdate, DocumentDownloadURL, DocumentPageRead, DocumentRead

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    account_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    if file.content_type not in settings.allowed_upload_mime_type_list:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}",
        )

    # account_id, if given, must actually belong to this user — otherwise
    # a user could attach an upload to someone else's account by guessing
    # a UUID.
    if account_id is not None:
        account = db.get(Account, account_id)
        if account is None or account.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    # Read into memory to enforce the size cap before ever touching
    # object storage — an UploadFile is already spooled to disk past a
    # threshold by Starlette, but the S3 PUT shouldn't start on an
    # oversized file only to fail partway through.
    contents = file.file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_upload_size_mb}MB limit",
        )
    if len(contents) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    document = Document(
        user_id=current_user.id,
        account_id=account_id,
        filename=file.filename or "unnamed",
        storage_path="",  # set below once we know the document's own id
        mime_type=file.content_type,
        status=DocumentStatus.uploaded,
    )
    db.add(document)
    db.flush()  # assigns document.id without committing yet

    storage_key = build_storage_key(str(current_user.id), str(document.id), document.filename)
    document.storage_path = storage_key

    try:
        upload_file(storage_key, contents, file.content_type)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Object storage upload failed")

    db.commit()
    db.refresh(document)

    process_document.delay(str(document.id))

    return document


@router.get("", response_model=list[DocumentRead])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Document]:
    stmt = (
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.user_id != current_user.id:
        # 404, not 403 — confirming a document id exists but belongs to
        # someone else still leaks information.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.get("/{document_id}/download-url", response_model=DocumentDownloadURL)
def get_download_url(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentDownloadURL:
    document = db.get(Document, document_id)
    if document is None or document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    expires_in = 300
    url = generate_download_url(document.storage_path, expires_in_seconds=expires_in)
    return DocumentDownloadURL(url=url, expires_in_seconds=expires_in)


@router.get("/{document_id}/pages", response_model=list[DocumentPageRead])
def list_document_pages(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentPage]:
    """
    Exposes Phase 2's extraction output directly — this is the evidence
    layer the spec's explainability requirement calls for (§14: answers
    should be traceable to source document/page, not just an LLM's say-so).
    """
    document = db.get(Document, document_id)
    if document is None or document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    stmt = (
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number)
    )
    return list(db.execute(stmt).scalars().all())


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document_account(
    document_id: uuid.UUID,
    body: DocumentAccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """
    Assigns (or reassigns) the account a document belongs to. Needed
    because upload allows account_id=None (Phase 1), but Phase 3
    normalization requires an account — a Transaction row's account_id
    is NOT NULL by design (every transaction belongs to a real account).
    Does not itself trigger re-normalization; call POST
    /{document_id}/normalize afterward.
    """
    document = db.get(Document, document_id)
    if document is None or document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    account = db.get(Account, body.account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    document.account_id = account.id
    db.commit()
    db.refresh(document)
    return document


@router.post("/{document_id}/normalize", response_model=DocumentRead)
def trigger_normalization(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    """
    Manually (re-)triggers Phase 3 normalization — for a document whose
    account was just assigned post-upload, or to re-run after any other
    fix. Synchronous (not queued via Celery) so the caller gets the
    actual up-to-date status back immediately; normalization for a
    single document is not expensive enough to need async dispatch here,
    unlike the OCR-heavy extraction step.
    """
    document = db.get(Document, document_id)
    if document is None or document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if document.status != DocumentStatus.processed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document extraction is not complete (status: {document.status.value})",
        )

    normalize_document.apply(args=[str(document.id)])
    db.refresh(document)
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    document = db.get(Document, document_id)
    if document is None or document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    delete_file(document.storage_path)
    db.delete(document)
    db.commit()
