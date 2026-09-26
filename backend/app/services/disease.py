"""病害登记业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "disease"
REQUIRED_FIELDS = ["病害编号", "所在设施", "病害类型"]
STATUS_ORDER = ["待定级", "已定级", "处置中", "已闭环", "已挂起"]
ACTION_RULES = {"确认定级": "已定级", "提交闭环": "已闭环", "挂起病害": "已挂起"}
NEGATIVE_ACTIONS = []

# 批量定级：定级必填项、严重等级允许取值、以及不允许批量改动的状态
GRADE_REQUIRED_FIELDS = ["严重等级", "定级结论"]
SEVERITY_LEVELS = ["轻微", "一般", "较重", "严重"]
LOCKED_STATUSES = ["已闭环", "已挂起"]


class DiseaseService:
    def __init__(self) -> None:
        # 已处理的定级批次：批次号 -> 首次处理结果；重复提交同一批次直接回执，不产生重复记录
        self._graded_batches: dict[str, dict[str, Any]] = {}

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("病害编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"病害记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于病害登记可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"病害记录已{action}"

    def batch_grade(self, batch_no: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """一次提交给多条病害定级：逐条处理、逐条回执，单条不合格不影响其余记录。"""
        batch_no = batch_no.strip()
        if not batch_no:
            return {"ok": False, "batch_no": batch_no, "duplicated": False,
                    "message": "批次号不能为空，请填写本次验收的定级批次号", "receipts": []}
        if not items:
            return {"ok": False, "batch_no": batch_no, "duplicated": False,
                    "message": "批量定级至少包含一条病害记录", "receipts": []}
        if batch_no in self._graded_batches:
            stored = self._graded_batches[batch_no]
            return {**stored, "duplicated": True,
                    "message": f"批次 {batch_no} 已提交过，按首次处理结果回执，未重复定级"}
        receipts: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for item in items:
            receipts.append(self._grade_one(item, batch_no=batch_no, seen_ids=seen_ids))
        graded = sum(1 for receipt in receipts if receipt["result"] == "已定级")
        rejected = len(receipts) - graded
        result = {
            "ok": True,
            "batch_no": batch_no,
            "duplicated": False,
            "message": f"批量定级完成：已定级 {graded} 条，退回 {rejected} 条",
            "receipts": receipts,
        }
        self._graded_batches[batch_no] = result
        return result

    def _grade_one(self, item: dict[str, Any], *, batch_no: str, seen_ids: set[int]) -> dict[str, Any]:
        entry = self._resolve_entry(item)
        if entry is None:
            return self._receipt(item.get("entry_id"), item.get("病害编号"), "已退回", "病害记录",
                                 "病害记录不存在或已归档，无法定级")
        entry_id = int(entry.get("id", 0))
        code = str(entry.get("病害编号") or "")
        if entry_id in seen_ids:
            return self._receipt(entry_id, code, "已退回", "病害记录", "同一批次内重复提交，已忽略该条")
        seen_ids.add(entry_id)
        status = str(entry.get("status") or "")
        if status in LOCKED_STATUSES:
            return self._receipt(entry_id, code, "已退回", "病害状态", f"病害{status}，不能批量改动")
        for field in GRADE_REQUIRED_FIELDS:
            if not str(item.get(field) or "").strip():
                self._mark_rejected(entry, f"{field}未填写")
                return self._receipt(entry_id, code, "已退回", field, f"{field}未填写，定级退回")
        level = str(item.get("严重等级") or "").strip()
        if level not in SEVERITY_LEVELS:
            self._mark_rejected(entry, f"严重等级「{level}」不在允许范围")
            return self._receipt(entry_id, code, "已退回", "严重等级",
                                 f"严重等级须为：{'、'.join(SEVERITY_LEVELS)}")
        conclusion = str(item.get("定级结论") or "").strip()
        # 定级结论、严重等级直接写在病害记录上，列表与详情读同一条数据，显示保持一致
        entry["严重等级"] = level
        entry["定级结论"] = conclusion
        entry["status"] = "已定级"
        entry["病害状态"] = "已定级"
        entry["pending"] = True
        entry["abnormal"] = False
        entry["定级批次"] = batch_no
        entry["定级日期"] = date.today().isoformat()
        entry.pop("退回原因", None)
        return self._receipt(entry_id, code, "已定级", None, f"定级成功：{level}，{conclusion}")

    @staticmethod
    def _resolve_entry(item: dict[str, Any]) -> dict[str, Any] | None:
        entry_id = item.get("entry_id")
        if entry_id is not None:
            try:
                return store.find(MODULE, int(entry_id))
            except (TypeError, ValueError):
                return None
        code = str(item.get("病害编号") or "").strip()
        if code:
            for row in store.rows(MODULE):
                if str(row.get("病害编号") or "") == code:
                    return row
        return None

    @staticmethod
    def _mark_rejected(entry: dict[str, Any], reason: str) -> None:
        # 被退回的病害留在列表里可查：状态不动，只在记录上标注退回原因
        entry["退回原因"] = reason
        entry["abnormal"] = True

    @staticmethod
    def _receipt(entry_id: Any, code: Any, result: str, field: str | None, message: str) -> dict[str, Any]:
        return {"entry_id": entry_id, "病害编号": code, "result": result,
                "不合格项": field, "message": message}
