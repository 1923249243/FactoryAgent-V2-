import logging
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from app.agent import llm as llm_service
from app.agent.session import (
    get_pending_work_order,
    is_cancellation_message,
    is_confirmation_message,
    pop_pending_work_order,
    set_pending_work_order,
)
from app.agent.tools import (
    build_work_order_proposal,
    create_work_order,
    get_machine_status,
    get_maintenance_records,
    normalize_machine_code,
    search_manual_tool,
)
from app.agent.tracing import persist_agent_trace
from app.drawing.service import (
    create_drawing,
    get_drawing,
    latest_drawing_id,
    revise_drawing,
)


logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    message: str
    session_id: str
    run_id: str
    route: str
    machine_code: str
    tool_results: list[dict]
    answer: str
    requires_confirmation: bool
    trace: list[dict[str, Any]]


def append_trace(
    state: AgentState,
    node: str,
    event_type: str,
    detail: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [
        *state["trace"],
        {
            "node": node,
            "event_type": event_type,
            "detail": detail or {},
        },
    ]


def keyword_route(message: str) -> str:
    """Local routing fallback used without a key or when the model fails."""

    if any(item in message for item in ["创建工单", "建工单", "维修工单", "报修"]):
        return "create_work_order"
    if any(item in message for item in ["修改", "改成", "改为", "调整", "重新生成"]):
        if any(item in message for item in ["孔", "孔径", "直径", "厚度", "尺寸", "设计", "图纸"]):
            return "drawing_modify"
    if any(item in message for item in ["装配体", "减速器", "PX-2100", "assembly"]):
        if any(item in message for item in ["修改", "改成", "改为", "调整"]):
            return "drawing_modify"
        return "drawing_create_assembly"
    if any(item in message for item in ["画一个", "绘制", "三视图", "等轴测", "工程图", "DXF", "STEP", "STL", "BOM", "安装板", "法兰", "支架", "箱体"]):
        if any(item in message for item in ["修改", "改成", "改为", "调整", "重新生成"]):
            return "drawing_modify"
        if any(item in message for item in ["输出", "导出", "下载"]):
            return "drawing_export"
        return "drawing_create_part"
    if any(item in message for item in ["维修记录", "维修历史", "维护记录", "保养记录"]):
        return "maintenance_records"
    if any(item in message for item in ["手册", "说明书", "知识库", "怎么处理", "如何处理"]):
        return "manual_search"
    if any(item in message for item in ["报警", "状态", "为什么", "温度", "故障"]):
        return "machine_diagnosis"
    return "general"


def router(state: AgentState) -> AgentState:
    message = state["message"]
    pending = get_pending_work_order(state["session_id"])

    if pending and is_confirmation_message(message):
        route = "confirm_work_order"
        route_source = "pending_confirmation"
    elif pending and is_cancellation_message(message):
        route = "cancel_work_order"
        route_source = "pending_cancellation"
    else:
        llm_route = llm_service.classify_intent(message)
        route = llm_route or keyword_route(message)
        route_source = "llm" if llm_route else "keyword_fallback"

    return {
        **state,
        "route": route,
        "machine_code": normalize_machine_code(message),
        "trace": append_trace(
            state,
            "router",
            "route_selected",
            {"route": route, "source": route_source},
        ),
    }


def machine_diagnosis_node(state: AgentState) -> AgentState:
    code = state["machine_code"]
    status = get_machine_status(code)
    records = get_maintenance_records(code) if code else []
    manual = search_manual_tool(state["message"])

    return {
        **state,
        "tool_results": [
            status,
            {"records": records},
            {"manual": manual},
        ],
        "trace": append_trace(
            state,
            "machine_diagnosis",
            "tools_completed",
            {
                "machine_code": code,
                "maintenance_record_count": len(records),
                "manual_hit_count": len(manual),
            },
        ),
    }


def maintenance_records_node(state: AgentState) -> AgentState:
    code = state["machine_code"]
    status = get_machine_status(code)
    records = get_maintenance_records(code) if code else []
    return {
        **state,
        "tool_results": [status, {"records": records}],
        "trace": append_trace(
            state,
            "maintenance_records",
            "tools_completed",
            {"machine_code": code, "maintenance_record_count": len(records)},
        ),
    }


def manual_search_node(state: AgentState) -> AgentState:
    manual = search_manual_tool(state["message"])
    return {
        **state,
        "tool_results": [{"manual": manual}],
        "trace": append_trace(
            state,
            "manual_search",
            "tool_completed",
            {"manual_hit_count": len(manual)},
        ),
    }


def create_work_order_node(state: AgentState) -> AgentState:
    code = state["machine_code"]
    status = get_machine_status(code)
    if "error" in status:
        return {
            **state,
            "tool_results": [status],
            "requires_confirmation": False,
            "trace": append_trace(
                state,
                "create_work_order",
                "proposal_rejected",
                {"reason": status["error"]},
            ),
        }

    proposal = build_work_order_proposal(code, state["message"], status)
    set_pending_work_order(state["session_id"], proposal)
    return {
        **state,
        "tool_results": [status, {"work_order_proposal": proposal}],
        "requires_confirmation": True,
        "trace": append_trace(
            state,
            "create_work_order",
            "confirmation_requested",
            {
                "machine_code": proposal["machine_code"],
                "reason": proposal["reason"],
            },
        ),
    }


def confirm_work_order_node(state: AgentState) -> AgentState:
    proposal = get_pending_work_order(state["session_id"])
    if not proposal:
        return {
            **state,
            "tool_results": [{"error": "没有待确认的维修工单。"}],
            "requires_confirmation": False,
            "trace": append_trace(
                state,
                "confirm_work_order",
                "confirmation_missing",
            ),
        }

    order = create_work_order(proposal["machine_code"], proposal["reason"])
    pop_pending_work_order(state["session_id"])
    return {
        **state,
        "tool_results": [{"pending_work_order": proposal}, order],
        "requires_confirmation": False,
        "trace": append_trace(
            state,
            "confirm_work_order",
            "work_order_created",
            {"work_order_id": order["work_order_id"]},
        ),
    }


def cancel_work_order_node(state: AgentState) -> AgentState:
    proposal = pop_pending_work_order(state["session_id"])
    if not proposal:
        return {
            **state,
            "tool_results": [{"error": "没有待确认的维修工单。"}],
            "requires_confirmation": False,
            "trace": append_trace(
                state,
                "cancel_work_order",
                "cancellation_missing",
            ),
        }
    return {
        **state,
        "tool_results": [{"work_order_cancelled": True, "proposal": proposal}],
        "requires_confirmation": False,
        "trace": append_trace(
            state,
            "cancel_work_order",
            "work_order_cancelled",
            {"machine_code": proposal["machine_code"]},
        ),
    }


def drawing_node(state: AgentState) -> AgentState:
    route = state["route"]
    try:
        if route in {"drawing_create_part", "drawing_create_assembly"}:
            record = create_drawing(state["message"])
        elif route == "drawing_modify":
            drawing_id = latest_drawing_id()
            if not drawing_id:
                raise ValueError("没有可修改的绘图，请先创建一个零件或装配体。")
            record = revise_drawing(drawing_id, state["message"])
        else:
            drawing_id = latest_drawing_id()
            if not drawing_id:
                raise ValueError("没有可导出的绘图，请先创建一个零件或装配体。")
            record = get_drawing(drawing_id)
        tool_results = [record]
        event_type = "drawing_completed"
        detail = {
            "drawing_id": record.get("drawing_id"),
            "revision": record.get("revision"),
            "drawing_type": record.get("drawing_type"),
        }
    except Exception as exc:
        tool_results = [{"error": str(exc)}]
        event_type = "drawing_failed"
        detail = {"error": str(exc)}
    return {
        **state,
        "tool_results": tool_results,
        "trace": append_trace(state, "drawing_agent", event_type, detail),
    }


def general_node(state: AgentState) -> AgentState:
    return {
        **state,
        "tool_results": [],
        "trace": append_trace(state, "general", "no_tools_required"),
    }


def answer_node(state: AgentState) -> AgentState:
    answer = llm_service.generate_answer(
        user_message=state["message"],
        route=state["route"],
        tool_results=state["tool_results"],
    )
    return {
        **state,
        "answer": answer,
        "trace": append_trace(
            state,
            "answer_generation",
            "answer_created",
            {
                "llm_enabled": llm_service.llm_available(),
                "answer_length": len(answer),
            },
        ),
    }


def choose_route(state: AgentState) -> str:
    return state["route"]


graph = StateGraph(AgentState)

graph.add_node("router", router)
graph.add_node("machine_diagnosis", machine_diagnosis_node)
graph.add_node("maintenance_records", maintenance_records_node)
graph.add_node("manual_search", manual_search_node)
graph.add_node("create_work_order", create_work_order_node)
graph.add_node("confirm_work_order", confirm_work_order_node)
graph.add_node("cancel_work_order", cancel_work_order_node)
graph.add_node("drawing_agent", drawing_node)
graph.add_node("general", general_node)
graph.add_node("answer_generation", answer_node)

graph.set_entry_point("router")

graph.add_conditional_edges(
    "router",
    choose_route,
    {
        "machine_diagnosis": "machine_diagnosis",
        "maintenance_records": "maintenance_records",
        "manual_search": "manual_search",
        "create_work_order": "create_work_order",
        "confirm_work_order": "confirm_work_order",
        "cancel_work_order": "cancel_work_order",
        "drawing_create_part": "drawing_agent",
        "drawing_create_assembly": "drawing_agent",
        "drawing_modify": "drawing_agent",
        "drawing_export": "drawing_agent",
        "drawing_explain": "drawing_agent",
        "general": "general",
    },
)

for node_name in [
    "machine_diagnosis",
    "maintenance_records",
    "manual_search",
    "create_work_order",
    "confirm_work_order",
    "cancel_work_order",
    "drawing_agent",
    "general",
]:
    graph.add_edge(node_name, "answer_generation")

graph.add_edge("answer_generation", END)

agent_graph = graph.compile()


def run_agent(message: str, session_id: str = "default") -> AgentState:
    run_id = str(uuid4())
    initial_state: AgentState = {
        "message": message,
        "session_id": session_id,
        "run_id": run_id,
        "route": "",
        "machine_code": "",
        "tool_results": [],
        "answer": "",
        "requires_confirmation": False,
        "trace": [],
    }
    result = agent_graph.invoke(initial_state)
    try:
        persist_agent_trace(
            run_id=result["run_id"],
            session_id=result["session_id"],
            message=result["message"],
            route=result["route"],
            events=result["trace"],
        )
    except Exception as exc:
        # Observability must not make a successful business request fail.
        logger.warning("Could not persist agent trace: %s", exc)
    return result
