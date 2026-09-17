from datetime import datetime
import json
from typing import Any

from app.db import get_conn


TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message TEXT NOT NULL,
    route TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_trace_events (
    run_id TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    node TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, event_index),
    FOREIGN KEY (run_id) REFERENCES agent_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_trace_events_run_id
    ON agent_trace_events(run_id, event_index);
"""


def persist_agent_trace(
    run_id: str,
    session_id: str,
    message: str,
    route: str,
    events: list[dict[str, Any]],
) -> None:
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.executescript(TRACE_SCHEMA)
        conn.execute(
            """
            INSERT OR REPLACE INTO agent_runs(
                run_id, session_id, message, route, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, session_id, message, route, created_at),
        )
        conn.execute(
            "DELETE FROM agent_trace_events WHERE run_id = ?",
            (run_id,),
        )
        conn.executemany(
            """
            INSERT INTO agent_trace_events(
                run_id, event_index, node, event_type, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    index,
                    event.get("node", "unknown"),
                    event.get("event_type", "unknown"),
                    json.dumps(event.get("detail", {}), ensure_ascii=False, default=str),
                    created_at,
                )
                for index, event in enumerate(events)
            ],
        )


def get_agent_trace(run_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        conn.executescript(TRACE_SCHEMA)
        run = conn.execute(
            """
            SELECT run_id, session_id, message, route, created_at
            FROM agent_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run is None:
            return None

        events = conn.execute(
            """
            SELECT event_index, node, event_type, detail_json, created_at
            FROM agent_trace_events
            WHERE run_id = ?
            ORDER BY event_index
            """,
            (run_id,),
        ).fetchall()

    return {
        **dict(run),
        "events": [
            {
                "event_index": event["event_index"],
                "node": event["node"],
                "event_type": event["event_type"],
                "detail": json.loads(event["detail_json"]),
                "created_at": event["created_at"],
            }
            for event in events
        ],
    }
