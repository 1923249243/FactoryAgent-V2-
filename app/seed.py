from pathlib import Path
from app.db import get_conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    temperature REAL,
    alarm_code TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS maintenance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_code TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_code TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS manual_docs USING fts5(
    source,
    content
);
"""

def seed():
    Path("data").mkdir(exist_ok=True)

    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM machines")
        conn.execute("DELETE FROM maintenance_records")
        conn.execute("DELETE FROM work_orders")
        conn.execute("DELETE FROM manual_docs")

        conn.executemany(
            """
            INSERT INTO machines(code, name, status, temperature, alarm_code, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("CNC-001", "1号数控机床", "running", 47.5, None, "2026-09-17 20:00:00"),
                ("CNC-002", "2号数控机床", "idle", 38.2, None, "2026-09-17 20:00:00"),
                ("CNC-003", "3号数控机床", "alarm", 86.7, "SPINDLE_OVERHEAT", "2026-09-17 20:00:00"),
            ],
        )

        conn.executemany(
            """
            INSERT INTO maintenance_records(machine_code, description, created_at)
            VALUES (?, ?, ?)
            """,
            [
                ("CNC-003", "2026-08-21 更换主轴冷却风扇。", "2026-08-21 10:15:00"),
                ("CNC-003", "2026-09-02 检查冷却液液位，补充冷却液。", "2026-09-02 14:30:00"),
                ("CNC-001", "2026-09-10 完成日常润滑维护。", "2026-09-10 09:00:00"),
            ],
        )

        manual_dir = Path("data/manuals")
        manual_dir.mkdir(parents=True, exist_ok=True)

        for path in manual_dir.glob("*.txt"):
            content = path.read_text(encoding="utf-8")
            conn.execute(
                "INSERT INTO manual_docs(source, content) VALUES (?, ?)",
                (path.name, content),
            )

    print("Database seeded successfully.")

if __name__ == "__main__":
    seed()
