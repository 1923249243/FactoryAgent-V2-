from fastapi import FastAPI, HTTPException

from app.agent.graph import run_agent
from app.agent.tools import (
    get_machine_status,
    get_maintenance_records,
    list_machines,
    list_work_orders,
    normalize_machine_code,
)
from app.schemas import (
    ChatRequest,
    ChatResponse,
    MaintenanceRecordResponse,
    MachineResponse,
    WorkOrderResponse,
)


app = FastAPI(
    title="FactoryAgent",
    version="1.1.0",
    description=(
        "Manufacturing AI Agent demo with FastAPI, LangGraph, SQLite, "
        "OpenAI-compatible LLM and RAG."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/machines", response_model=list[MachineResponse])
def machines() -> list[dict]:
    return list_machines()


def _path_machine_code(machine_code: str) -> str:
    return normalize_machine_code(machine_code) or machine_code.upper()


@app.get("/machines/{machine_code}", response_model=MachineResponse)
def machine(machine_code: str) -> dict:
    code = _path_machine_code(machine_code)
    result = get_machine_status(code)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get(
    "/machines/{machine_code}/maintenance",
    response_model=list[MaintenanceRecordResponse],
)
def machine_maintenance(machine_code: str) -> list[dict]:
    code = _path_machine_code(machine_code)
    status = get_machine_status(code)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return get_maintenance_records(code)


@app.get("/work-orders", response_model=list[WorkOrderResponse])
def work_orders() -> list[dict]:
    return list_work_orders()


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        result = run_agent(req.message, session_id=req.session_id)
        return ChatResponse(
            answer=result["answer"],
            route=result["route"],
            tool_results=result["tool_results"],
            requires_confirmation=result["requires_confirmation"],
            session_id=req.session_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
