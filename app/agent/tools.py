from datetime import datetime
import re
from typing import Any

from app.db import get_conn
from app.rag.retriever import search_manual


def normalize_machine_code(text: str) -> str:
    mapping = {
        "1号": "CNC-001",
        "一号": "CNC-001",
        "2号": "CNC-002",
        "二号": "CNC-002",
        "3号": "CNC-003",
        "三号": "CNC-003",
    }
    for key, value in mapping.items():
        if key in text:
            return value

    upper = text.upper()
    match = re.search(r"CNC[-_ ]?(\d{1,3})", upper)
    if match:
        return f"CNC-{int(match.group(1)):03d}"

    return ""


def list_machines() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT code, name, status, temperature, alarm_code, updated_at
            FROM machines
            ORDER BY code
            """
        ).fetchall()

    return [dict(row) for row in rows]


def get_machine_status(machine_code: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT code, name, status, temperature, alarm_code, updated_at
            FROM machines
            WHERE code = ?
            """,
            (machine_code,),
        ).fetchone()

    if not row:
        return {"error": f"machine {machine_code} not found"}
    return dict(row)


def get_maintenance_records(
    machine_code: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT machine_code, description, created_at
            FROM maintenance_records
            WHERE machine_code = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (machine_code, limit),
        ).fetchall()

    return [dict(r) for r in rows]


def list_work_orders() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, machine_code, reason, status, created_at
            FROM work_orders
            ORDER BY id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def extract_work_order_reason(message: str) -> str:
    patterns = [
        r"(?:原因是|原因：|原因:|因为|由于|故障是|故障为)\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            reason = re.split(r"[。！？!?\n]", match.group(1), maxsplit=1)[0]
            reason = reason.strip(" ：:,，")
            if reason:
                return reason
    return "用户申请设备维修，待现场确认具体故障"


def build_work_order_proposal(
    machine_code: str,
    message: str,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    machine = status or get_machine_status(machine_code)
    if "error" in machine:
        return machine

    return {
        "work_order_id": None,
        "machine_code": machine_code,
        "machine_name": machine["name"],
        "reason": extract_work_order_reason(message),
        "status": "pending_confirmation",
        "proposed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def create_work_order(machine_code: str, reason: str) -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO work_orders(machine_code, reason, status, created_at)
            VALUES (?, ?, 'open', ?)
            """,
            (machine_code, reason, now),
        )
        work_order_id = cur.lastrowid

    return {
        "work_order_id": work_order_id,
        "machine_code": machine_code,
        "reason": reason,
        "status": "open",
        "created_at": now,
    }


def search_manual_tool(query: str) -> list[dict[str, Any]]:
    return search_manual(query)
