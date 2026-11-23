"""同期群运营圈选接口：未回访回查、范围领取、名单生成、迟到回访确认与来源回算。

路由挂在 /api/cohort_analysis/ops 下，必须在通用资源路由之前注册，
避免 /api/{module}/{entry_id} 抢先匹配。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas import ActionResult, PageResult
from app.services.cohort_ops import cohort_ops_service

router = APIRouter(prefix="/api/cohort_analysis/ops", tags=["同期群运营圈选"])


class ClaimPayload(BaseModel):
    群组编号: str
    观察日: int
    渠道: str


class OplistPayload(BaseModel):
    圈选条件: dict[str, str] = Field(default_factory=dict)


class RevisitReportPayload(BaseModel):
    群组编号: str
    观察日: int
    用户IDs: list[str] = Field(default_factory=list)


class RevisitConfirmPayload(BaseModel):
    群组编号: str
    观察日: int


@router.get("/members")
def actual_members(
    群组编号: str = Query(...),
    观察日: int = Query(..., ge=1),
    渠道: str | None = Query(default=None),
) -> dict:
    """按观察日和渠道查询实际入群成员，逐行标注回访状态与回访批次。"""
    return cohort_ops_service.actual_members(群组编号, 观察日, 渠道 or None)


@router.get("/absent")
def absent_members(
    群组编号: str = Query(...),
    观察日: int = Query(..., ge=1),
    渠道: str = Query(...),
) -> dict:
    """未回访成员清单：候选行与已回访人数都标出采用的回访批次。"""
    return cohort_ops_service.absent_members(群组编号, 观察日, 渠道)


@router.post("/claims", response_model=ActionResult)
def claim_scope(payload: ClaimPayload) -> ActionResult:
    """领取未回访范围：以当前回访批次为领取边界快照候选用户。"""
    claim = cohort_ops_service.claim_scope(payload.群组编号, payload.观察日, payload.渠道)
    return ActionResult(
        ok=True,
        message=(
            f"已领取第 {claim['观察日']} 日「{claim['渠道']}」未回访范围，"
            f"边界批次 {claim['回访批次']}，候选 {len(claim['候选用户'])} 人"
        ),
        entry=claim,
    )


@router.get("/claims", response_model=PageResult[dict])
def list_claims() -> PageResult[dict]:
    items = cohort_ops_service.list_claims()
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.post("/claims/{claim_id}/oplists", response_model=ActionResult)
def generate_oplist(claim_id: str, payload: OplistPayload) -> ActionResult:
    """在领取范围内按用户属性圈选，组装运营名单；每轮领取只生成一份。"""
    oplist, message = cohort_ops_service.generate_oplist(claim_id, payload.圈选条件)
    return ActionResult(ok=oplist is not None, message=message, entry=oplist)


@router.post("/revisits", response_model=ActionResult)
def report_revisits(payload: RevisitReportPayload) -> ActionResult:
    """补送迟到回访（待确认），重复用户只算一人。"""
    records, message = cohort_ops_service.report_revisits(
        payload.群组编号, payload.观察日, payload.用户IDs)
    return ActionResult(
        ok=records is not None, message=message,
        entry={"records": records} if records is not None else None,
    )


@router.post("/revisits/confirm", response_model=ActionResult)
def confirm_revisits(payload: RevisitConfirmPayload) -> ActionResult:
    """确认待确认回访：生成新回访批次，后续领取与名单采用新批次。"""
    batch, message = cohort_ops_service.confirm_revisits(payload.群组编号, payload.观察日)
    return ActionResult(ok=batch is not None, message=message, entry=batch)


@router.get("/oplists", response_model=PageResult[dict])
def list_oplists() -> PageResult[dict]:
    items = cohort_ops_service.list_oplists()
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.get("/oplists/{list_id}/source")
def oplist_source(list_id: str) -> dict:
    """回查名单来源：按实际采用的回访批次与渠道回算并校验一致性。"""
    source = cohort_ops_service.oplist_source(list_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"运营名单 {list_id} 不存在")
    return source
