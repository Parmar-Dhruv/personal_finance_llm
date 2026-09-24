"""
Minimal Accounts CRUD.

Not a Phase 3 deliverable in its own right — this closes a gap that
predates Phase 3 (the `Account` model has existed since Phase 0/1 with
no API to create one at all) but was never noticed until Phase 3's
normalization flow needed a real account_id to attach documents to.
Kept intentionally minimal (create + list); update/delete deferred to
whichever phase actually owns account management.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import Account, User
from app.schemas.account import AccountCreate, AccountRead

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Account:
    account = Account(
        user_id=current_user.id,
        name=payload.name,
        institution=payload.institution,
        account_type=payload.account_type,
        currency=payload.currency.upper(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("", response_model=list[AccountRead])
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Account]:
    stmt = select(Account).where(Account.user_id == current_user.id).order_by(Account.created_at)
    return list(db.execute(stmt).scalars().all())
