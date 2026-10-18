"""
Minimal categories API (create + list).

Same story as accounts.py: Phase 4's category summaries and category
budgets are unusable without a way to create categories and assign them,
and the Phase 5 classifier will write the same `Transaction.category_id`
column. Update/delete are deliberately absent — see Known Gaps.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_visible_category
from app.db.base import get_db
from app.db.models import Category, User
from app.schemas.category import CategoryCreate, CategoryRead

router = APIRouter(prefix="/categories", tags=["categories"])

MAX_CATEGORY_DEPTH = 3  # root = depth 1


def _depth(db: Session, category: Category) -> int:
    depth, cursor, seen = 1, category, {category.id}
    while cursor.parent_id is not None and cursor.parent_id not in seen:
        cursor = db.get(Category, cursor.parent_id)
        seen.add(cursor.id)
        depth += 1
    return depth


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Category:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Category name is blank")

    if payload.parent_id is not None:
        parent = get_visible_category(db, current_user, payload.parent_id)
        if _depth(db, parent) >= MAX_CATEGORY_DEPTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Categories can be nested at most {MAX_CATEGORY_DEPTH} levels deep",
            )

    # A user category may not shadow a system (or their own) category of the
    # same name at the same level. The DB unique index also guards own-scope
    # duplicates race-free; this check is what covers system-vs-user.
    clash = db.execute(
        select(Category.id).where(
            or_(Category.user_id.is_(None), Category.user_id == current_user.id),
            Category.parent_id.is_not_distinct_from(payload.parent_id),
            func.lower(Category.name) == name.lower(),
        )
    ).first()
    if clash is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with that name already exists here")

    category = Category(user_id=current_user.id, parent_id=payload.parent_id, name=name, is_system=False)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with that name already exists here")
    db.refresh(category)
    return category


@router.get("", response_model=list[CategoryRead])
def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Category]:
    stmt = (
        select(Category)
        .where(or_(Category.user_id.is_(None), Category.user_id == current_user.id))
        .order_by(Category.is_system.desc(), func.lower(Category.name))
    )
    return list(db.execute(stmt).scalars().all())
