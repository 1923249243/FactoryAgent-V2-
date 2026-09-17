from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", min_length=1, max_length=100)


class ChatResponse(BaseModel):
    answer: str
    route: str
    tool_results: list[dict[str, Any]]
    requires_confirmation: bool = False
    session_id: str = "default"
    run_id: str = ""
    trace: list[dict[str, Any]] = Field(default_factory=list)


class MachineResponse(BaseModel):
    code: str
    name: str
    status: str
    temperature: float | None = None
    alarm_code: str | None = None
    updated_at: str


class MaintenanceRecordResponse(BaseModel):
    machine_code: str
    description: str
    created_at: str


class WorkOrderResponse(BaseModel):
    id: int
    machine_code: str
    reason: str
    status: str
    created_at: str


class TraceEventResponse(BaseModel):
    event_index: int
    node: str
    event_type: str
    detail: dict[str, Any]
    created_at: str


class AgentTraceResponse(BaseModel):
    run_id: str
    session_id: str
    message: str
    route: str
    created_at: str
    events: list[TraceEventResponse]
