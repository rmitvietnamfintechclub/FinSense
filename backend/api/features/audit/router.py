from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.api.features.audit.guard import AdminDep
from backend.api.features.audit.schemas import (
    AuditAction,
    AuditActionResult,
    AuditArticles,
    AuditLog,
    AuditSort,
    AuditStatus,
    AuditSummary,
)
from backend.api.features.audit.service import (
    ClusterSourceNotFoundError,
    InvalidAuditActionError,
    apply_audit_action,
    get_audit_articles,
    get_audit_log,
    get_audit_summary,
)
from backend.core.database_async import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


def db_dep() -> AsyncIOMotorDatabase:
    return get_db()


DbDep = Annotated[AsyncIOMotorDatabase, Depends(db_dep)]
PageDep = Annotated[int, Query(ge=1)]


@router.get("/summary", response_model=AuditSummary)
async def read_summary(admin: AdminDep, db: DbDep) -> AuditSummary:
    return await get_audit_summary(db)


@router.get("/articles", response_model=AuditArticles)
async def read_articles(
    admin: AdminDep,
    db: DbDep,
    status_filter: AuditStatus = Query(AuditStatus.PENDING, alias="status"),
    sort: AuditSort = Query(AuditSort.NEWEST),
    search: str | None = Query(None),
    page: PageDep = 1,
) -> AuditArticles:
    """`status` is aliased because `status` shadows fastapi's imported status
    module inside this function body."""
    return await get_audit_articles(
        db, status=status_filter, sort=sort, search=search, page=page
    )


@router.patch("/events/{cluster_id}/{source}", response_model=AuditActionResult)
async def audit_source(
    cluster_id: str,
    source: str,
    action: AuditAction,
    admin: AdminDep,
    db: DbDep,
) -> AuditActionResult:
    """admin comes from the JWT via AdminDep — the body cannot claim an identity,
    so audit_log always records who actually made the call."""
    try:
        return await apply_audit_action(db, cluster_id, source, action, admin)
    except ClusterSourceNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except InvalidAuditActionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/log", response_model=AuditLog)
async def read_log(admin: AdminDep, db: DbDep, page: PageDep = 1) -> AuditLog:
    return await get_audit_log(db, page=page)
