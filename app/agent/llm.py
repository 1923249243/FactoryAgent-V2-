import json
import logging
import re
from typing import Any

from openai import OpenAI

from app.config import settings


logger = logging.getLogger(__name__)

VALID_ROUTES = {
    "machine_diagnosis",
    "maintenance_records",
    "manual_search",
    "create_work_order",
    "general",
}


def llm_available() -> bool:
    return bool(
        settings.llm_api_key.strip()
        and settings.llm_base_url.strip()
        and settings.llm_model.strip()
    )


def _request_completion(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    response_format: dict[str, str] | None = None,
) -> str | None:
    if not llm_available():
        return None

    request_kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format is not None:
        request_kwargs["response_format"] = response_format

    try:
        client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        response = client.chat.completions.create(**request_kwargs)
    except Exception as exc:
        # Some older OpenAI-compatible gateways do not implement JSON mode.
        # Retry once without that optional parameter, but never retry network
        # or authentication failures indefinitely.
        if response_format is not None and "response_format" in str(exc).lower():
            request_kwargs.pop("response_format", None)
            try:
                response = client.chat.completions.create(**request_kwargs)
            except Exception as retry_exc:
                logger.warning("LLM request failed; using fallback: %s", retry_exc)
                return None
        else:
            logger.warning("LLM request failed; using fallback: %s", exc)
            return None

    try:
        content = response.choices[0].message.content
    except Exception as exc:
        logger.warning("Invalid LLM response; using fallback: %s", exc)
        return None
    return content.strip() if content else None


def _parse_route(content: str | None) -> str | None:
    if not content:
        return None

    candidate = content.strip()
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None
    route = payload.get("route") or payload.get("intent")
    return route if route in VALID_ROUTES else None


def classify_intent(message: str) -> str | None:
    """Ask the configured model for a validated, structured route."""

    content = _request_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是制造业设备运维路由器。只输出 JSON，不要输出解释。"
                    '{"route":"..."}。route 只能是：'
                    "machine_diagnosis、maintenance_records、manual_search、"
                    "create_work_order、general。"
                ),
            },
            {"role": "user", "content": message},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return _parse_route(content)


def generate_answer(
    user_message: str,
    route: str,
    tool_results: list[dict[str, Any]],
) -> str:
    if not llm_available():
        return fallback_answer(route, tool_results)

    context = json.dumps(tool_results, ensure_ascii=False, default=str)
    content = _request_completion(
        [
            {"role": "system", "content": "你是可靠的制造业设备运维助手。"},
            {
                "role": "user",
                "content": f"""
用户问题：
{user_message}

系统路由：
{route}

工具和知识库结果：
{context}

要求：
1. 只根据工具和知识库结果回答，不要编造。
2. 设备诊断必须明确写出当前状态、报警代码、温度、近期维修记录、手册中的可能原因和建议操作。
3. 工单处于待确认状态时，不得声称已经写入数据库，只能展示拟创建信息并请求用户确认。
4. 工单已创建时，明确给出工单号。
5. 中文回答，尽量简洁。
""",
            },
        ],
        temperature=0.2,
    )
    return content or fallback_answer(route, tool_results)


def _first_result(tool_results: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next((item for item in tool_results if key in item), {})


def _manual_sections(manual: list[dict[str, Any]]) -> tuple[str, str]:
    text = "\n".join(str(item.get("snippet", "")) for item in manual)
    if not text:
        return "", ""

    causes = text
    advice = ""
    if "常见原因" in text:
        causes = text.split("常见原因", 1)[1]
    if "处理建议" in causes:
        causes, advice = causes.split("处理建议", 1)
    return (
        causes.strip(" ：:\n").rstrip("。；; "),
        advice.strip(" ：:\n"),
    )


def fallback_answer(route: str, tool_results: list[dict[str, Any]]) -> str:
    error = next((item.get("error") for item in tool_results if "error" in item), None)
    if error:
        return f"无法完成请求：{error}。请检查设备编号或先初始化数据库。"

    if route == "create_work_order":
        proposal_wrapper = _first_result(tool_results, "work_order_proposal")
        proposal = proposal_wrapper.get("work_order_proposal", proposal_wrapper)
        if proposal:
            return (
                f"拟创建维修工单：设备 {proposal.get('machine_code')} "
                f"（{proposal.get('machine_name')}），原因：{proposal.get('reason')}。"
                "请回复“确认”后写入数据库，回复“取消”可放弃。"
            )

    if route == "confirm_work_order":
        order = _first_result(tool_results, "work_order_id")
        if order:
            return (
                f"已创建维修工单 #{order.get('work_order_id')}，"
                f"设备 {order.get('machine_code')}，原因：{order.get('reason')}。"
            )

    if route == "cancel_work_order":
        return "已取消本次待确认的维修工单，数据库未写入新记录。"

    if route == "machine_diagnosis":
        status = _first_result(tool_results, "name")
        records = _first_result(tool_results, "records").get("records", [])
        manual = _first_result(tool_results, "manual").get("manual", [])
        if not status:
            return "未找到对应设备，无法生成诊断结果。"

        causes, advice = _manual_sections(manual)
        parts = [
            "设备诊断结果：",
            f"当前设备状态：{status.get('status')}。",
            f"报警代码：{status.get('alarm_code') or '无'}。",
            f"温度：{status.get('temperature')}℃。",
        ]
        if records:
            parts.append(
                "近期维修记录："
                + "；".join(
                    record["description"].rstrip("。；; ")
                    for record in records[:5]
                )
                + "。"
            )
        else:
            parts.append("近期维修记录：暂无记录。")
        parts.append(f"手册中的可能原因：{causes or '暂无匹配内容'}。")
        parts.append(
            f"建议操作：{advice or '停止高负载加工，检查冷却风扇、冷却液、温度传感器和主轴轴承。'}"
        )
        return "".join(parts)

    if route == "maintenance_records":
        records = _first_result(tool_results, "records").get("records", [])
        if not records:
            return "该设备暂无维修记录。"
        return "近期维修记录：" + "；".join(
            record["description"] for record in records
        )

    if route == "manual_search":
        manual = _first_result(tool_results, "manual").get("manual", [])
        if manual:
            return "知识库检索结果：" + "；".join(
                str(item.get("snippet", "")) for item in manual
            )
        return "知识库中没有检索到足够相关的内容。"

    return "我可以帮你查询设备状态、维修记录、设备手册，或者创建维修工单。"
