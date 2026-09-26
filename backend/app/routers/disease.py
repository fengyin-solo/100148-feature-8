"""病害登记接口：维护病害记录，覆盖确认定级、批量定级、提交闭环、挂起病害等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchGradePayload, BatchGradeResult, EntryPayload, PageResult
from app.services.disease import DiseaseService

router = APIRouter(prefix="/api/disease", tags=["病害登记"])

service = DiseaseService()

LIST_FIELDS = ["病害编号", "所在设施", "病害类型", "病害位置", "严重等级", "定级结论", "发现日期", "登记人员", "病害状态"]
STATUSES = ["待定级", "已定级", "处置中", "已闭环", "已挂起"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按病害编号检索"),
    status: str | None = Query(default=None, description="待定级、已定级、处置中、已闭环、已挂起"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按病害编号与状态过滤病害登记列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条病害记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"病害记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条病害记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="病害记录已登记", entry=entry)


@router.post("/batch-grade", response_model=BatchGradeResult)
def batch_grade(payload: BatchGradePayload) -> BatchGradeResult:
    """一次提交给多条病害定级：逐条回执已定级或被退回；同一批次号重复提交不产生重复记录。"""
    result, message = service.batch_grade(payload.batch_no, payload.items)
    if result is None:
        return BatchGradeResult(ok=False, message=message, batch_no=payload.batch_no)
    return BatchGradeResult(ok=True, message=message, batch_no=result["batch_no"], receipts=result["receipts"])


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条病害记录执行确认定级、提交闭环、挂起病害；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出病害登记清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "disease", "total": total, "items": items}
