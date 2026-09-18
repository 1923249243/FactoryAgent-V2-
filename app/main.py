from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.agent.graph import run_agent
from app.agent.tools import (
    get_machine_status,
    get_maintenance_records,
    list_machines,
    list_work_orders,
    normalize_machine_code,
)
from app.agent.tracing import get_agent_trace
from app.drawing.service import (
    DrawingNotFoundError,
    artifact_file,
    create_drawing,
    get_drawing,
    list_drawing_ids,
    revise_drawing,
)
from app.drawing.validator import DrawingValidationError
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.models.result import EngineeringResult
from app.engineering.catalog import catalog_payload, get_catalog_motor
from app.engineering.planner import EngineeringPlanner
from app.engineering.schemas import (
    EngineeringDesignRequest,
    EngineeringReport,
    EngineeringRevisionRequest,
    EngineeringSimulationRequest,
    GripperDesignRequest,
)
from app.engineering.service import (
    EngineeringDesignNotFoundError,
    create_engineering_object,
    create_gripper_design,
    engineering_artifact,
    generic_artifact,
    get_gripper_design,
    get_engineering_design,
    list_engineering_templates,
    revise_engineering_object,
    simulate_engineering_object,
)
from app.schemas import (
    AgentTraceResponse,
    ChatRequest,
    ChatResponse,
    DrawingCreateRequest,
    DrawingResponse,
    DrawingRevisionRequest,
    MaintenanceRecordResponse,
    MachineResponse,
    WorkOrderResponse,
)


app = FastAPI(
    title="FactoryAgent",
    version="4.3.0",
    description=(
        "Manufacturing maintenance and deterministic parametric drawing Agent "
        "with FastAPI, LangGraph, SQLite, OpenAI-compatible LLM, CAD export "
        "deterministic engineering validation and provenance evidence."
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


@app.get("/traces/{run_id}", response_model=AgentTraceResponse)
def trace(run_id: str) -> dict:
    result = get_agent_trace(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"trace {run_id} not found")
    return result


@app.get("/drawings", response_model=list[str])
def drawings() -> list[str]:
    return list_drawing_ids()


@app.post("/drawings", response_model=DrawingResponse)
def create_drawing_endpoint(req: DrawingCreateRequest) -> dict:
    try:
        return create_drawing(req.prompt)
    except DrawingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"drawing generation failed: {exc}") from exc


@app.post("/drawings/{drawing_id}/revise", response_model=DrawingResponse)
def revise_drawing_endpoint(drawing_id: str, req: DrawingRevisionRequest) -> dict:
    try:
        return revise_drawing(drawing_id, req.prompt)
    except DrawingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"drawing {drawing_id} not found") from exc
    except DrawingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"drawing revision failed: {exc}") from exc


@app.get("/drawings/{drawing_id}", response_model=DrawingResponse)
def drawing_detail(drawing_id: str) -> dict:
    try:
        return get_drawing(drawing_id)
    except DrawingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"drawing {drawing_id} not found") from exc


def _drawing_file(drawing_id: str, artifact: str, media_type: str) -> FileResponse:
    try:
        path = artifact_file(drawing_id, artifact)
    except (DrawingNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"drawing artifact not found: {artifact}") from exc
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/drawings/{drawing_id}/sheet")
def drawing_sheet(drawing_id: str) -> FileResponse:
    return _drawing_file(drawing_id, "sheet", "image/svg+xml")


@app.get("/drawings/{drawing_id}/sheet.png")
def drawing_sheet_png(drawing_id: str) -> FileResponse:
    return _drawing_file(drawing_id, "png", "image/png")


@app.get("/drawings/{drawing_id}/svg")
def drawing_svg(drawing_id: str) -> FileResponse:
    return _drawing_file(drawing_id, "svg", "image/svg+xml")


@app.get("/drawings/{drawing_id}/dxf")
def drawing_dxf(drawing_id: str) -> FileResponse:
    return _drawing_file(drawing_id, "dxf", "application/dxf")


@app.get("/drawings/{drawing_id}/step")
def drawing_step(drawing_id: str) -> FileResponse:
    return _drawing_file(drawing_id, "step", "application/step")


@app.get("/drawings/{drawing_id}/stl")
def drawing_stl(drawing_id: str) -> FileResponse:
    return _drawing_file(drawing_id, "stl", "model/stl")


@app.get("/drawings/{drawing_id}/bom")
def drawing_bom(drawing_id: str) -> FileResponse:
    return _drawing_file(drawing_id, "bom", "application/json")


@app.post("/engineering/grippers", response_model=EngineeringReport)
def create_gripper_design_endpoint(req: GripperDesignRequest) -> dict:
    try:
        return create_gripper_design(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"engineering design failed: {exc}") from exc


@app.get("/engineering/grippers/{design_id}", response_model=EngineeringReport)
def gripper_design_detail(design_id: str) -> dict:
    try:
        return get_gripper_design(design_id)
    except (EngineeringDesignNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"engineering design not found: {design_id}") from exc


def _engineering_file(design_id: str, artifact: str, media_type: str) -> FileResponse:
    try:
        path = engineering_artifact(design_id, artifact)
    except (EngineeringDesignNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"engineering artifact not found: {artifact}") from exc
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/engineering/grippers/{design_id}/step")
def gripper_step(design_id: str) -> FileResponse:
    return _engineering_file(design_id, "step", "application/step")


@app.get("/engineering/grippers/{design_id}/stl")
def gripper_stl(design_id: str) -> FileResponse:
    return _engineering_file(design_id, "stl", "model/stl")


@app.get("/engineering/grippers/{design_id}/report")
def gripper_report(design_id: str) -> FileResponse:
    return _engineering_file(design_id, "report", "application/json")


@app.get("/engineering/grippers/{design_id}/motion")
def gripper_motion(design_id: str) -> FileResponse:
    return _engineering_file(design_id, "motion", "application/json")


@app.get("/engineering/grippers/{design_id}/provenance")
def gripper_provenance(design_id: str) -> FileResponse:
    return _engineering_file(design_id, "provenance", "application/json")


@app.post("/engineering/designs", response_model=EngineeringResult)
def create_engineering_design_endpoint(req: EngineeringDesignRequest) -> dict:
    try:
        if req.spec is not None:
            spec = req.spec
            requested = req.requested_capabilities or None
        else:
            assert req.prompt is not None
            planned = EngineeringPlanner().plan(req.prompt)
            if planned.spec is None:
                spec = EngineeringObjectSpec(
                    object_type="mechanism",
                    template="unsupported",
                    name=req.prompt,
                    metadata={"planner_errors": planned.errors},
                )
                requested = req.requested_capabilities or planned.requested_capabilities or None
            else:
                spec = planned.spec
                requested = req.requested_capabilities or planned.requested_capabilities or None
        return create_engineering_object(spec, requested_capabilities=requested)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"engineering design failed: {exc}") from exc


@app.get("/engineering/templates")
def engineering_templates() -> list[dict]:
    return list_engineering_templates()


@app.get("/engineering/motors")
def engineering_motors() -> list[dict]:
    """List manufacturer-backed motor candidates known to the local catalog."""

    return catalog_payload()


@app.get("/engineering/motors/{catalog_id}")
def engineering_motor_detail(catalog_id: str) -> dict:
    motor = get_catalog_motor(catalog_id)
    if motor is None:
        raise HTTPException(status_code=404, detail=f"motor catalog item not found: {catalog_id}")
    return motor.model_dump(mode="json")


@app.get("/engineering/designs/{design_id}", response_model=EngineeringResult)
def engineering_design_detail(design_id: str) -> dict:
    try:
        return get_engineering_design(design_id)
    except (EngineeringDesignNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"engineering design not found: {design_id}") from exc


@app.post("/engineering/designs/{design_id}/revise", response_model=EngineeringResult)
def revise_engineering_design_endpoint(
    design_id: str,
    req: EngineeringRevisionRequest,
) -> dict:
    try:
        return revise_engineering_object(design_id, req)
    except EngineeringDesignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"engineering design not found: {design_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"engineering revision failed: {exc}") from exc


@app.post("/engineering/designs/{design_id}/simulate", response_model=EngineeringResult)
def simulate_engineering_design_endpoint(
    design_id: str,
    req: EngineeringSimulationRequest | None = None,
) -> dict:
    try:
        return simulate_engineering_object(design_id, req)
    except EngineeringDesignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"engineering design not found: {design_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"engineering simulation failed: {exc}") from exc


def _generic_engineering_file(design_id: str, artifact: str, media_type: str) -> FileResponse:
    try:
        path = generic_artifact(design_id, artifact)
    except (EngineeringDesignNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"engineering artifact not found: {artifact}") from exc
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/engineering/designs/{design_id}/report")
def engineering_design_report(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "report", "application/json")


@app.get("/engineering/designs/{design_id}/step")
def engineering_design_step(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "step", "application/step")


@app.get("/engineering/designs/{design_id}/stl")
def engineering_design_stl(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "stl", "model/stl")


@app.get("/engineering/designs/{design_id}/drawing")
def engineering_design_drawing(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "drawing", "image/svg+xml")


@app.get("/engineering/designs/{design_id}/sheet")
def engineering_design_sheet(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "sheet", "image/svg+xml")


@app.get("/engineering/designs/{design_id}/sheet.png")
def engineering_design_sheet_png(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "png", "image/png")


@app.get("/engineering/designs/{design_id}/dxf")
def engineering_design_dxf(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "dxf", "application/dxf")


@app.get("/engineering/designs/{design_id}/bom")
def engineering_design_bom(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "bom", "application/json")


@app.get("/engineering/designs/{design_id}/assembly-constraints")
def engineering_design_assembly_constraints(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "assembly_constraints", "application/json")


@app.get("/engineering/designs/{design_id}/freecad")
def engineering_design_freecad_recipe(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "freecad_recipe", "text/x-python")


@app.get("/engineering/designs/{design_id}/fem-plan")
def engineering_design_fem_plan(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "fem_plan", "application/json")


@app.get("/engineering/designs/{design_id}/fem-template")
def engineering_design_fem_template(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "fem_template", "text/plain")


@app.get("/engineering/designs/{design_id}/provenance")
def engineering_design_provenance(design_id: str) -> FileResponse:
    return _generic_engineering_file(design_id, "provenance", "application/json")


@app.post("/engineering/designs/{design_id}/fem", response_model=EngineeringResult)
def engineering_design_fem(
    design_id: str,
    req: EngineeringSimulationRequest | None = None,
) -> dict:
    try:
        requested = [
            "geometry",
            "selection",
            "assembly",
            "kinematics",
            "interference",
            "fem",
            "drawing",
            "export",
        ]
        if req is not None and req.requested_capabilities:
            requested = req.requested_capabilities
            if "fem" not in requested:
                requested.append("fem")
        return simulate_engineering_object(
            design_id,
            EngineeringSimulationRequest(requested_capabilities=requested),
        )
    except EngineeringDesignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"engineering design not found: {design_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"engineering FEM handoff failed: {exc}") from exc


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
            run_id=result["run_id"],
            trace=result["trace"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
