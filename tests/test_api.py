import os
import importlib

os.environ["DATABASE_PATH"] = "data/test_factory_agent.db"

from fastapi.testclient import TestClient

from app.agent import llm as llm_service
from app.agent import session as session_store
from app.agent.session import clear_pending_work_orders
from app.config import settings
from app.main import app
from app.seed import seed

client = TestClient(app)

def setup_module():
    settings.llm_api_key = ""
    clear_pending_work_orders()
    seed()

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_trace_is_returned_and_persisted():
    r = client.post(
        "/chat",
        json={
            "message": "3号机床今天为什么报警？",
            "session_id": "trace-test",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["run_id"]
    assert data["trace"][0]["node"] == "router"
    assert any(item["node"] == "answer_generation" for item in data["trace"])

    persisted = client.get(f"/traces/{data['run_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["run_id"] == data["run_id"]
    persisted_events = [
        (event["node"], event["event_type"], event["detail"])
        for event in persisted.json()["events"]
    ]
    response_events = [
        (event["node"], event["event_type"], event["detail"])
        for event in data["trace"]
    ]
    assert persisted_events == response_events


def test_pending_work_order_is_sqlite_persistent():
    proposal = {
        "machine_code": "CNC-003",
        "machine_name": "3号数控机床",
        "reason": "主轴过热",
        "status": "pending_confirmation",
        "proposed_at": "2026-09-17 21:30:00",
    }
    session_store.set_pending_work_order("sqlite-persistence", proposal)
    importlib.reload(session_store)
    loaded = session_store.get_pending_work_order("sqlite-persistence")
    assert loaded is not None
    assert loaded["machine_code"] == "CNC-003"
    assert loaded["reason"] == "主轴过热"
    session_store.pop_pending_work_order("sqlite-persistence")

def test_machine_diagnosis():
    r = client.post("/chat", json={"message": "3号机床今天为什么报警？"})
    assert r.status_code == 200
    data = r.json()
    assert data["route"] == "machine_diagnosis"
    assert "CNC-003" in str(data["tool_results"])
    assert "SPINDLE_OVERHEAT" in str(data["tool_results"])
    assert "冷却风扇" in str(data["tool_results"])

def test_create_work_order():
    r = client.post(
        "/chat",
        json={"message": "帮我给3号机床创建一个维修工单，原因是主轴过热"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["route"] == "create_work_order"
    assert "工单" in data["answer"]
    assert data["requires_confirmation"] is True
    assert "CNC-003" in data["answer"]
    assert "None" not in data["answer"]


def test_machines_list():
    r = client.get("/machines")
    assert r.status_code == 200
    assert [machine["code"] for machine in r.json()] == [
        "CNC-001",
        "CNC-002",
        "CNC-003",
    ]


def test_machine_detail():
    r = client.get("/machines/CNC-003")
    assert r.status_code == 200
    assert r.json()["alarm_code"] == "SPINDLE_OVERHEAT"
    assert r.json()["temperature"] == 86.7


def test_machine_maintenance_endpoint():
    r = client.get("/machines/CNC-003/maintenance")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_maintenance_records_route():
    r = client.post(
        "/chat",
        json={
            "message": "请查询3号机床的维修记录",
            "session_id": "maintenance-route",
        },
    )
    assert r.status_code == 200
    assert r.json()["route"] == "maintenance_records"
    assert "冷却风扇" in r.json()["answer"]


def test_manual_rag_has_content():
    r = client.post(
        "/chat",
        json={
            "message": "请查看3号机床说明书中的主轴过热处理建议",
            "session_id": "manual-rag",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["route"] == "manual_search"
    assert "冷却风扇" in str(data["tool_results"])


def test_llm_unavailable_fallback():
    r = client.post(
        "/chat",
        json={
            "message": "3号机床今天为什么报警？",
            "session_id": "fallback",
        },
    )
    assert r.status_code == 200
    assert r.json()["route"] == "machine_diagnosis"
    assert "当前设备状态" in r.json()["answer"]


def test_llm_structured_route(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def fake_completion(messages, **kwargs):
        if kwargs.get("response_format"):
            return '{"route":"maintenance_records"}'
        return "模型回答"

    monkeypatch.setattr(llm_service, "_request_completion", fake_completion)
    r = client.post(
        "/chat",
        json={
            "message": "请帮我看一下设备历史数据",
            "session_id": "llm-route",
        },
    )
    assert r.status_code == 200
    assert r.json()["route"] == "maintenance_records"


def test_llm_api_failure_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def broken_client(**kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(llm_service, "OpenAI", broken_client)
    r = client.post(
        "/chat",
        json={
            "message": "3号机床今天为什么报警？",
            "session_id": "llm-outage",
        },
    )
    assert r.status_code == 200
    assert r.json()["route"] == "machine_diagnosis"
    assert "报警代码" in r.json()["answer"]


def test_create_work_order_confirmation():
    session_id = "confirmation-flow"
    first = client.post(
        "/chat",
        json={
            "message": "给3号机床建个维修工单，原因是主轴过热",
            "session_id": session_id,
        },
    )
    assert first.status_code == 200
    assert first.json()["requires_confirmation"] is True
    assert "确认" in first.json()["answer"]
    assert client.get("/work-orders").json() == []

    second = client.post(
        "/chat",
        json={"message": "确认", "session_id": session_id},
    )
    assert second.status_code == 200
    assert second.json()["route"] == "confirm_work_order"
    assert second.json()["requires_confirmation"] is False
    assert "已创建维修工单" in second.json()["answer"]
    orders = client.get("/work-orders").json()
    assert len(orders) == 1
    assert orders[0]["machine_code"] == "CNC-003"


def test_invalid_machine_number():
    r = client.get("/machines/CNC-999")
    assert r.status_code == 404
