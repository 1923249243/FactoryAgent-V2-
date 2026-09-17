from typing import TypedDict

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


class AgentState(TypedDict):
    message: str
    session_id: str
    route: str
    machine_code: str
    tool_results: list[dict]
    answer: str
    requires_confirmation: bool


def keyword_route(message: str) -> str:
    """Local routing fallback used without a key or when the model fails."""

    if any(item in message for item in ["创建工单", "建工单", "维修工单", "报修"]):
        return "create_work_order"
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
    elif pending and is_cancellation_message(message):
        route = "cancel_work_order"
    else:
        route = llm_service.classify_intent(message) or keyword_route(message)

    return {
        **state,
        "route": route,
        "machine_code": normalize_machine_code(message),
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
    }


def maintenance_records_node(state: AgentState) -> AgentState:
    code = state["machine_code"]
    status = get_machine_status(code)
    records = get_maintenance_records(code) if code else []
    return {
        **state,
        "tool_results": [status, {"records": records}],
    }


def manual_search_node(state: AgentState) -> AgentState:
    manual = search_manual_tool(state["message"])
    return {**state, "tool_results": [{"manual": manual}]}


def create_work_order_node(state: AgentState) -> AgentState:
    code = state["machine_code"]
    status = get_machine_status(code)
    if "error" in status:
        return {
            **state,
            "tool_results": [status],
            "requires_confirmation": False,
        }

    proposal = build_work_order_proposal(code, state["message"], status)
    set_pending_work_order(state["session_id"], proposal)
    return {
        **state,
        "tool_results": [status, {"work_order_proposal": proposal}],
        "requires_confirmation": True,
    }


def confirm_work_order_node(state: AgentState) -> AgentState:
    proposal = get_pending_work_order(state["session_id"])
    if not proposal:
        return {
            **state,
            "tool_results": [{"error": "没有待确认的维修工单。"}],
            "requires_confirmation": False,
        }

    order = create_work_order(proposal["machine_code"], proposal["reason"])
    pop_pending_work_order(state["session_id"])
    return {
        **state,
        "tool_results": [{"pending_work_order": proposal}, order],
        "requires_confirmation": False,
    }


def cancel_work_order_node(state: AgentState) -> AgentState:
    proposal = pop_pending_work_order(state["session_id"])
    if not proposal:
        return {
            **state,
            "tool_results": [{"error": "没有待确认的维修工单。"}],
            "requires_confirmation": False,
        }
    return {
        **state,
        "tool_results": [{"work_order_cancelled": True, "proposal": proposal}],
        "requires_confirmation": False,
    }


def general_node(state: AgentState) -> AgentState:
    return {**state, "tool_results": []}


def answer_node(state: AgentState) -> AgentState:
    answer = llm_service.generate_answer(
        user_message=state["message"],
        route=state["route"],
        tool_results=state["tool_results"],
    )
    return {**state, "answer": answer}


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
    "general",
]:
    graph.add_edge(node_name, "answer_generation")

graph.add_edge("answer_generation", END)

agent_graph = graph.compile()


def run_agent(message: str, session_id: str = "default") -> AgentState:
    initial_state: AgentState = {
        "message": message,
        "session_id": session_id,
        "route": "",
        "machine_code": "",
        "tool_results": [],
        "answer": "",
        "requires_confirmation": False,
    }
    return agent_graph.invoke(initial_state)
