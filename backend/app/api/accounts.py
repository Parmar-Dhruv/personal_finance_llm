"""
Minimal Accounts API.

Create + list come from the Phase 3 gap patch (the `Account` model had no API
at all until normalization needed a real account_id). Phase 6 adds exactly one
more capability, the starting balance the forecast projects from, as
`PUT/DELETE /accounts/{id}/balance` rather than a general PATCH, so it is
obvious this does not (yet) edit anything else. Rename/deactivate/delete are
still unowned by any phase (see Known Gaps).
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_account
from app.db.base import get_db
from app.db.models import Account, User
from app.schemas.account import AccountBalanceSet, AccountCreate, AccountRead

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


@router.put("/{account_id}/balance", response_model=AccountRead)
def set_account_balance(
    account_id: uuid.UUID,
    payload: AccountBalanceSet,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Account:
    """
    Set the balance the forecast starts from. Only the user can know this
    number (nothing in the schema carries a balance), so a wrong value gives
    wrong projected balances; the forecast says where its balance came from.
    """
    account = get_owned_account(db, current_user, account_id)  # 404 if not theirs
    account.opening_balance = payload.opening_balance
    account.balance_as_of = payload.balance_as_of
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}/balance", response_model=AccountRead)
def clear_account_balance(
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Account:
    """Forget the balance; forecasts for this account become flow-only. Idempotent."""
    account = get_owned_account(db, current_user, account_id)
    account.opening_balance = None
    account.balance_as_of = None
    db.commit()
    db.refresh(account)
    return account
