import json
from datetime import datetime, timezone
from threading import Lock

import httpx

from app.core.config import settings


_status_lock = Lock()
_runtime_status = {
    "state": "configured" if settings.llm_api_key else "disabled",
    "error": None,
    "last_failure_at": None,
}


def get_llm_status(include_diagnostics: bool = False) -> dict:
    with _status_lock:
        state = _runtime_status["state"]
        if not settings.llm_api_key:
            state = "disabled"
        elif state == "disabled":
            state = "configured"
    labels = {
        "disabled": "大模型未配置，正在使用本地对话模式",
        "configured": "大模型已配置，等待首次调用验证",
        "connected": "大模型已连接",
        "degraded": "大模型调用失败，已切换本地对话模式",
    }
    payload = {
        "mode": "llm" if settings.llm_api_key else "local",
        "state": state,
        "model": settings.llm_model if settings.llm_api_key else None,
        "label": labels[state],
    }
    if include_diagnostics:
        payload["last_error"] = _runtime_status["error"]
        payload["last_failure_at"] = _runtime_status["last_failure_at"]
    return payload


def _set_status(state: str, error: str | None = None) -> None:
    with _status_lock:
        _runtime_status.update(
            state=state,
            error=error,
            last_failure_at=datetime.now(timezone.utc).isoformat() if error else _runtime_status["last_failure_at"],
        )


def _failure_reason(exc: Exception) -> str:
    """Return an administrator-safe failure category without request URLs or credentials."""
    if isinstance(exc, httpx.TimeoutException):
        return "模型请求超时"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"模型服务返回 HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "模型服务网络请求失败"
    if isinstance(exc, (KeyError, IndexError, TypeError, ValueError)):
        return "模型响应格式无效或为空"
    return type(exc).__name__


def _call_model(system_prompt: str, messages: list[dict], max_tokens: int | None = None, temperature: float = 0.5) -> str | None:
    if not settings.llm_api_key:
        _set_status("disabled")
        return None
    request_messages = [{"role": "system", "content": system_prompt}, *messages[-12:]]
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
                json={
                    "model": settings.llm_model,
                    "messages": request_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens or settings.llm_max_tokens,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
        if not content:
            raise ValueError("模型返回空内容")
        _set_status("connected")
        return content
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        _set_status("degraded", _failure_reason(exc))
        return None


def generate_chat_reply(messages: list[dict], profile: dict) -> str | None:
    system_prompt = (
        "你是熟悉中国城市的旅行朋友和本地导游，不是只会收集条件的规划机器人。"
        "先直接回答用户当前的问题：问美食就介绍吃什么和适合去的街区，问季节就说明何时舒服，问景点就讲亮点和感受。"
        "语气温暖、自然、有一点画面感，像朋友在出发前给建议；通常用 2 到 4 句，不要重复上一轮内容。"
        "除非用户明确要求制定行程，否则不要把对话转成规划流程，也不要机械地追问天数和预算。"
        "可在确实有帮助时只追问一个轻松的问题。不得编造具体店铺、景点价格、开放时间、距离或交通数据。"
        "回复使用简洁中文。"
        f"\n当前用户画像：{json.dumps(profile, ensure_ascii=False)}"
    )
    return _call_model(system_prompt, messages)


def generate_itinerary_summary(requirement: dict, itinerary: dict) -> str | None:
    system_prompt = (
        "你是旅游行程说明助手。只能根据给定的已校验结构化数据写一段简洁中文交付说明。"
        "不得增加景点、价格、开放时间、路线距离或交通耗时。必须如实说明出行日期、路线和预算校验状态；"
        "预算只可称为估算，并明确结构化数据中的未包含项。"
    )
    content = json.dumps({"requirement": requirement, "itinerary": itinerary}, ensure_ascii=False)
    return _call_model(system_prompt, [{"role": "user", "content": content}], max_tokens=300)


def generate_replan_interpretation(instruction: str, itinerary: dict, attractions: list[dict]) -> dict | None:
    """Ask an optional LLM for a JSON proposal; callers must still validate every action."""
    system_prompt = (
        "你是行程修改意图解析器，只输出一个 JSON 对象，不能输出 Markdown 或解释。"
        "JSON 格式固定为："
        '{"status":"ready"|"needs_clarification","summary":"简短中文说明","actions":[...],"questions":[...]}. '
        "actions 只能使用 set_days(value 1-10)、set_budget(value 0-100000)、"
        "set_preferences(preferences 字符串数组)、remove_attraction(attraction_id)、"
        "replace_attraction(attraction_id,new_attraction_id)。景点 ID 必须来自给定数据。"
        "用户意图不完整、景点名称有歧义、想改动当前不支持的内容，必须返回 needs_clarification，"
        "actions 为空，并提出最多三个具体问题。不得编造景点、价格、路线或 ID。"
    )
    payload = json.dumps(
        {"instruction": instruction, "itinerary": itinerary, "available_attractions": attractions},
        ensure_ascii=False,
    )
    content = _call_model(system_prompt, [{"role": "user", "content": payload}], max_tokens=500, temperature=0)
    if not content:
        return None
    try:
        normalized = content.strip()
        if normalized.startswith("```"):
            normalized = normalized.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(normalized)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, IndexError, TypeError):
        return None
