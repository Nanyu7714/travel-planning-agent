import json
from threading import Lock

import httpx

from app.core.config import settings


_status_lock = Lock()
_runtime_status = {"state": "configured" if settings.llm_api_key else "disabled", "error": None}


def get_llm_status() -> dict:
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
    return {
        "mode": "llm" if settings.llm_api_key else "local",
        "state": state,
        "model": settings.llm_model if settings.llm_api_key else None,
        "label": labels[state],
    }


def _set_status(state: str, error: str | None = None) -> None:
    with _status_lock:
        _runtime_status.update(state=state, error=error)


def _call_model(system_prompt: str, messages: list[dict], max_tokens: int | None = None) -> str | None:
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
                    "temperature": 0.5,
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
        _set_status("degraded", type(exc).__name__)
        return None


def generate_chat_reply(messages: list[dict], profile: dict) -> str | None:
    system_prompt = (
        "你是行旅旅游规划助手。请像正常对话一样回应用户，并结合已保存的用户画像。"
        "不要每轮都追问目的地，不要声称已经生成行程。用户未明确要求规划时，先了解其旅行兴趣、"
        "饮食偏好、节奏和限制；可以自然地一次追问一个信息。用户明确要求规划时，只提示系统会先整理需求并让用户确认。"
        "不得编造景点价格、开放时间、距离或交通数据。回复简洁、自然，使用中文。"
        f"\n当前用户画像：{json.dumps(profile, ensure_ascii=False)}"
    )
    return _call_model(system_prompt, messages)


def generate_itinerary_summary(requirement: dict, itinerary: dict) -> str | None:
    system_prompt = (
        "你是旅游行程说明助手。只能根据给定的已校验结构化数据写一段简洁中文交付说明。"
        "不得增加景点、价格、开放时间、路线距离或交通耗时。必须明确日期与交通仍待确认，费用只包含门票。"
    )
    content = json.dumps({"requirement": requirement, "itinerary": itinerary}, ensure_ascii=False)
    return _call_model(system_prompt, [{"role": "user", "content": content}], max_tokens=300)
