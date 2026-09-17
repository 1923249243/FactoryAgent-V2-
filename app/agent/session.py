from typing import Any

from app.db import get_conn


PENDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_work_orders (
    session_id TEXT PRIMARY KEY,
    machine_code TEXT NOT NULL,
    machine_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    proposed_at TEXT NOT NULL
);
"""


def _proposal_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "work_order_id": None,
        "machine_code": row["machine_code"],
        "machine_name": row["machine_name"],
        "reason": row["reason"],
        "status": row["status"],
        "proposed_at": row["proposed_at"],
    }


def set_pending_work_order(session_id: str, proposal: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.executescript(PENDING_SCHEMA)
        conn.execute(
            """
            INSERT INTO pending_work_orders(
                session_id, machine_code, machine_name, reason, status, proposed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                machine_code = excluded.machine_code,
                machine_name = excluded.machine_name,
                reason = excluded.reason,
                status = excluded.status,
                proposed_at = excluded.proposed_at
            """,
            (
                session_id,
                proposal["machine_code"],
                proposal["machine_name"],
                proposal["reason"],
                proposal["status"],
                proposal["proposed_at"],
            ),
        )


def get_pending_work_order(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        conn.executescript(PENDING_SCHEMA)
        row = conn.execute(
            """
            SELECT machine_code, machine_name, reason, status, proposed_at
            FROM pending_work_orders
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    return _proposal_from_row(row)


def pop_pending_work_order(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        conn.executescript(PENDING_SCHEMA)
        row = conn.execute(
            """
            SELECT machine_code, machine_name, reason, status, proposed_at
            FROM pending_work_orders
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is not None:
            conn.execute(
                "DELETE FROM pending_work_orders WHERE session_id = ?",
                (session_id,),
            )
    return _proposal_from_row(row)


def clear_pending_work_orders() -> None:
    with get_conn() as conn:
        conn.executescript(PENDING_SCHEMA)
        conn.execute("DELETE FROM pending_work_orders")


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
