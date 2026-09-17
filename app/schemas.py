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
