"""病害登记业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "disease"
REQUIRED_FIELDS = ["病害编号", "所在设施", "病害类型"]
STATUS_ORDER = ["待定级", "已定级", "处置中", "已闭环", "已挂起"]
ACTION_RULES = {"确认定级": "已定级", "提交闭环": "已闭环", "挂起病害": "已挂起"}
NEGATIVE_ACTIONS = []

# 批量定级：定级结论与严重等级为必检项；已闭环、已挂起的病害不允许批量改动
GRADE_TARGET_STATUS = "已定级"
SEVERITY_LEVELS = ["轻微", "一般", "较重", "严重"]
PROTECTED_STATUSES = ["已闭环", "已挂起"]
BATCH_SIZE_LIMIT = 200


class DiseaseService:
    def __init__(self) -> None:
        # 批次号 -> 首次处理结果：重复提交同一批直接回放缓存，不产生重复记录
        self._grade_batches: dict[str, dict[str, Any]] = {}

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

    def batch_grade(self, batch_no: str, items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
        """一次提交给多条病害定级：逐条独立处理，一条不合格不影响其余条目。"""
        batch_no = str(batch_no or "").strip()
        if not batch_no:
            return None, "缺少批次号：无法保证重复提交不产生重复记录"
        if not items:
            return None, "批次中没有需要定级的病害"
        if len(items) > BATCH_SIZE_LIMIT:
            return None, f"单批最多 {BATCH_SIZE_LIMIT} 条，请拆分后再提交"
        cached = self._grade_batches.get(batch_no)
        if cached is not None:
            # 重复提交同一批：刷新回执里的记录快照后原样返回，不重复写入
            for receipt in cached["receipts"]:
                entry_id = receipt.get("entry_id")
                if isinstance(entry_id, int):
                    receipt["entry"] = store.find(MODULE, entry_id)
            return cached, f"批次 {batch_no} 已处理过，本次为重复提交，返回首次处理结果"
        receipts = [self._grade_one(batch_no, item) for item in items]
        graded = sum(1 for receipt in receipts if receipt["result"] == GRADE_TARGET_STATUS)
        rejected = len(receipts) - graded
        result = {"batch_no": batch_no, "receipts": receipts, "graded": graded, "rejected": rejected}
        self._grade_batches[batch_no] = result
        return result, f"批量定级完成：已定级 {graded} 条，被退回 {rejected} 条"

    def _grade_one(self, batch_no: str, item: dict[str, Any]) -> dict[str, Any]:
        try:
            entry_id: int | None = int(item.get("entry_id"))
        except (TypeError, ValueError):
            entry_id = None
        entry = store.find(MODULE, entry_id) if entry_id is not None else None
        if entry is None:
            return self._receipt(entry_id, None, "被退回", f"病害记录 {item.get('entry_id')} 不存在或已归档")
        if entry.get("status") in PROTECTED_STATUSES:
            return self._receipt(entry_id, entry, "被退回", f"病害{entry.get('status')}，不能批量改动")
        problems: list[str] = []
        severity = str(item.get("严重等级") or "").strip()
        conclusion = str(item.get("定级结论") or "").strip()
        if severity not in SEVERITY_LEVELS:
            problems.append(f"严重等级不合格（须为{'、'.join(SEVERITY_LEVELS)}之一）")
        if not conclusion:
            problems.append("定级结论不合格（不能为空）")
        if problems:
            # 被退回的病害留在列表里可查，退回原因写在记录上
            entry["退回原因"] = "；".join(problems)
            return self._receipt(entry_id, entry, "被退回", entry["退回原因"])
        entry["严重等级"] = severity
        entry["定级结论"] = conclusion
        entry["status"] = GRADE_TARGET_STATUS
        entry["病害状态"] = GRADE_TARGET_STATUS
        entry["pending"] = True
        entry["定级批次号"] = batch_no
        entry.pop("退回原因", None)
        return self._receipt(entry_id, entry, GRADE_TARGET_STATUS, f"定级完成：严重等级{severity}")

    @staticmethod
    def _receipt(entry_id: int | None, entry: dict[str, Any] | None, result: str, message: str) -> dict[str, Any]:
        return {
            "entry_id": entry_id,
            "病害编号": (entry or {}).get("病害编号"),
            "result": result,
            "message": message,
            "entry": dict(entry) if entry is not None else None,
        }
