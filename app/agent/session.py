from threading import Lock
from typing import Any


_pending_work_orders: dict[str, dict[str, Any]] = {}
_lock = Lock()


def set_pending_work_order(session_id: str, proposal: dict[str, Any]) -> None:
    with _lock:
        _pending_work_orders[session_id] = proposal


def get_pending_work_order(session_id: str) -> dict[str, Any] | None:
    with _lock:
        proposal = _pending_work_orders.get(session_id)
        return dict(proposal) if proposal else None


def pop_pending_work_order(session_id: str) -> dict[str, Any] | None:
    with _lock:
        proposal = _pending_work_orders.pop(session_id, None)
        return dict(proposal) if proposal else None


def clear_pending_work_orders() -> None:
    with _lock:
        _pending_work_orders.clear()


def is_confirmation_message(message: str) -> bool:
    normalized = message.strip().lower()
    return normalized in {
        "确认",
        "确认创建",
        "确认工单",
        "是",
        "好的",
        "同意",
        "执行",
        "提交",
        "创建吧",
        "可以",
    }


def is_cancellation_message(message: str) -> bool:
    normalized = message.strip().lower()
    return normalized in {
        "取消",
        "取消工单",
        "不要",
        "否",
        "不创建",
        "算了",
    }
