import asyncio
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal
from app.llm import generate_chat_reply, generate_itinerary_summary
from app.models import AgentEvent, Attraction, ChatMessage, ChatSession, City, Itinerary, ItineraryDay, ItineraryStop, ItineraryValidation, PlanningJob, UserProfile


CITY_NAMES = {"北京": "北京", "上海": "上海", "成都": "成都", "北京市": "北京", "上海市": "上海", "成都市": "成都", "蓉城": "成都"}
PROFILE_PREFERENCES = {
    "摄影": ["拍照", "摄影", "街拍", "拍风景"],
    "辣味美食": ["吃辣", "喜欢辣", "爱吃辣", "无辣不欢"],
    "美食": ["美食", "小吃", "探店"],
    "历史文化": ["历史", "文化", "博物馆", "古迹"],
    "自然风景": ["自然", "山水", "风景", "徒步"],
    "夜景": ["夜景", "夜游"],
    "购物": ["购物", "逛街"],
    "亲子": ["亲子", "带孩子", "带娃"],
    "轻松慢游": ["慢节奏", "轻松", "悠闲", "慢游"],
    "紧凑打卡": ["紧凑", "特种兵", "多打卡"],
}


def is_planning_request(text: str) -> bool:
    return bool(re.search(r"\d+\s*[天日]", text)) or any(word in text for word in ["规划", "行程", "路线", "安排", "攻略", "计划"])


def city_recommendation(city: City, db: Session) -> str:
    attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city.id).order_by(Attraction.id).limit(4)))
    highlights = "；".join(f"{item.name}（{item.description}）" for item in attractions)
    return f"{city.name}很适合城市漫游。第一次去可以先看看：{highlights}\n\n如果你想进一步规划，可以直接告诉我“帮我规划”，我会先收集条件并请你确认。"


def extract_name(text: str) -> str | None:
    if "我是谁" in text:
        return None
    match = re.search(r"(?:我叫|我是)\s*([^\s，。,.!?！？]{1,12})", text)
    return match.group(1) if match else None


def remembered_name(texts: list[str]) -> str | None:
    for text in reversed(texts):
        name = extract_name(text)
        if name:
            return name
    return None


def extract_profile_preferences(text: str) -> list[str]:
    preferences = []
    for preference, keywords in PROFILE_PREFERENCES.items():
        if any(keyword in text and f"不{keyword}" not in text for keyword in keywords):
            preferences.append(preference)
    return preferences


def get_user_profile(db: Session, user_id: int) -> UserProfile:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if not profile:
        profile = UserProfile(user_id=user_id, preferences=[], avoid_places=[])
        db.add(profile)
        db.flush()
    if profile.preferences is None:
        profile.preferences = []
    if profile.avoid_places is None:
        profile.avoid_places = []
    return profile


def update_user_profile(db: Session, profile: UserProfile, text: str) -> list[str]:
    name = extract_name(text)
    if name:
        profile.display_name = name
    current = list(profile.preferences or [])
    added = [item for item in extract_profile_preferences(text) if item not in current]
    profile.preferences = [*current, *added]
    db.commit()
    return added


def profile_payload(profile: UserProfile) -> dict:
    return {
        "display_name": profile.display_name,
        "preferences": list(profile.preferences or []),
        "avoid_places": list(profile.avoid_places or []),
    }


def local_chat_response(text: str, profile: UserProfile, added_preferences: list[str]) -> str:
    name = profile.display_name
    if extract_name(text):
        return f"记住了，我会称呼你为{name}。你也可以继续告诉我平时喜欢的旅行方式、食物或不想去的地方。"
    if added_preferences:
        preference_text = "、".join(added_preferences)
        if not name:
            return f"记住了，你喜欢{preference_text}。以后推荐时我会考虑这些偏好。顺便告诉我该怎么称呼你？"
        if "摄影" in added_preferences:
            return f"记住了，{name}，你喜欢摄影。你更爱拍城市建筑、自然风景，还是人文街巷？"
        if "辣味美食" in added_preferences:
            return f"记住了，{name}，你喜欢辣味美食。以后推荐餐饮和小吃区域时我会优先考虑，也会避免把不吃辣当成默认条件。"
        if not any(item in (profile.preferences or []) for item in ["轻松慢游", "紧凑打卡"]):
            return f"记住了，{name}，你喜欢{preference_text}。旅行时你更偏向轻松慢游，还是一天多打卡几个地方？"
        return f"记住了，{name}，你喜欢{preference_text}。需要规划时告诉我城市和大致天数，我会先整理条件给你确认。"
    if any(word in text for word in ["你好", "嗨", "在吗"]):
        return f"你好{f'，{name}' if name else ''}。我们可以先聊聊你喜欢的旅行方式，不着急马上做行程。"
    known = "、".join(profile.preferences or [])
    if known:
        return f"我记得你喜欢{known}。你可以继续聊旅行想法；需要我开始规划时，直接告诉我就可以。"
    return "我们可以先随便聊聊。你平时旅行最在意的是风景、美食、拍照，还是轻松的节奏？"


def emit(db: Session, session_id: int, event_type: str, data: dict) -> None:
    last = db.scalar(select(AgentEvent.event_id).where(AgentEvent.session_id == session_id).order_by(AgentEvent.event_id.desc())) or 0
    db.add(AgentEvent(session_id=session_id, event_id=last + 1, event_type=event_type, data=data))
    db.commit()


def extract_request(text: str, db: Session, previous_user_texts: list[str] | None = None) -> tuple[City | None, int, list[str]]:
    previous_user_texts = previous_user_texts or []
    city = None
    for candidate_text in [text, *reversed(previous_user_texts)]:
        for raw_name, normalized in CITY_NAMES.items():
            if raw_name in candidate_text:
                city = db.scalar(select(City).where(City.name == normalized))
                break
        if city:
            break
    day_match = re.search(r"(\d+)\s*[天日]", text)
    if not day_match:
        for candidate_text in reversed(previous_user_texts):
            day_match = re.search(r"(\d+)\s*[天日]", candidate_text)
            if day_match:
                break
    days = max(2, min(int(day_match.group(1)), 5)) if day_match else 3
    all_text = " ".join([*previous_user_texts, text])
    interests = [tag for tag in ["美食", "历史", "文化", "自然", "休闲", "亲子", "夜景", "购物"] if tag in all_text]
    return city, days, interests


def extract_plan_request(
    text: str,
    db: Session,
    previous_user_texts: list[str] | None = None,
    saved_preferences: list[str] | None = None,
    saved_avoid_places: list[str] | None = None,
) -> dict:
    previous_user_texts = previous_user_texts or []
    saved_preferences = saved_preferences or []
    saved_avoid_places = saved_avoid_places or []
    city, days, interests = extract_request(text, db, previous_user_texts)
    combined = " ".join([*previous_user_texts, text])
    preference_interests = [item for item in saved_preferences if item not in ["轻松慢游", "紧凑打卡"]]
    if preference_interests:
        interests = list(dict.fromkeys([*interests, *preference_interests]))
    interests = interests or ["文化", "美食"]
    pace = "balanced"
    if any(word in combined for word in ["慢节奏", "轻松", "悠闲", "休闲"]) or "轻松慢游" in saved_preferences:
        pace = "relaxed"
    elif any(word in combined for word in ["紧凑", "特种兵", "多安排", "打卡"]) or "紧凑打卡" in saved_preferences:
        pace = "packed"
    budget_match = re.search(r"预算\s*(?:约|是|为|在|控制在)?\s*[¥￥]?\s*(\d{2,7})", combined)
    traveler_match = re.search(r"(\d{1,2})\s*(?:人|位)", combined)
    return {
        "destination_city_id": city.id if city else None,
        "destination": city.name if city else None,
        "days": days,
        "budget_total": int(budget_match.group(1)) if budget_match else None,
        "budget_scope": "门票估算；交通和餐饮未计入",
        "interests": interests,
        "avoid_places": list(saved_avoid_places),
        "pace": pace,
        "traveler_count": int(traveler_match.group(1)) if traveler_match else 1,
        "transport": "public_transport",
        "start_date": None,
        "missing_optional": ["start_date", "route_data", "meal_cost"],
    }


def confirmation_message(requirement: dict) -> str:
    pace_name = {"relaxed": "轻松", "balanced": "适中", "packed": "紧凑"}.get(requirement["pace"], "适中")
    budget = f"，预算 ¥{requirement['budget_total']}" if requirement.get("budget_total") else ""
    interests = "、".join(requirement.get("interests") or [])
    return f"已整理你的旅行需求：{requirement['destination']} {requirement['days']} 天，{requirement['traveler_count']} 人，偏好 {interests}，{pace_name}节奏{budget}。请确认后再生成行程。"


def latest_confirmation(db: Session, session_id: int) -> ChatMessage | None:
    messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant").order_by(ChatMessage.id.desc())))
    return next((message for message in messages if (message.payload or {}).get("type") == "plan_confirm"), None)


def build_itinerary(db: Session, job: PlanningJob, requirement: dict) -> Itinerary:
    city = db.get(City, requirement.get("destination_city_id"))
    if not city or city.support_level != "full" or not city.planning_enabled:
        raise ValueError("当前目的地暂不支持完整行程规划")
    days = max(2, min(int(requirement.get("days", 3)), 5))
    interests = requirement.get("interests") or ["文化", "美食"]
    interest_tags = set(interests)
    if "摄影" in interest_tags:
        interest_tags.update(["文化", "自然", "夜景", "休闲"])
    if "辣味美食" in interest_tags:
        interest_tags.add("美食")
    if "历史文化" in interest_tags:
        interest_tags.update(["历史", "文化"])
    if "自然风景" in interest_tags:
        interest_tags.add("自然")
    avoid_places = requirement.get("avoid_places") or []
    attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city.id).order_by(Attraction.id)))
    attractions = [item for item in attractions if not any(avoid and avoid in item.name for avoid in avoid_places)]
    ranked = sorted(attractions, key=lambda item: (sum(tag in interest_tags for tag in (item.tags or [])), -item.ticket_price, -item.id), reverse=True)
    required_count = days * 2
    if not ranked:
        raise ValueError(f"{city.name}当前没有符合排除条件的可用景点，请调整不想去的地方后重试")
    selected = ranked[:required_count]
    day_selections: list[list[Attraction]] = [[] for _ in range(days)]
    for index, attraction in enumerate(selected):
        day_selections[index % days].append(attraction)
    traveler_count = max(1, int(requirement.get("traveler_count", 1)))
    ticket_estimate = sum(item.ticket_price for item in selected) * traveler_count
    requested_budget = requirement.get("budget_total")
    itinerary = Itinerary(
        user_id=db.scalar(select(ChatSession.user_id).where(ChatSession.id == job.session_id)),
        session_id=job.session_id,
        title=f"{city.name}{days}日个性行程",
        city_name=city.name,
        days=days,
        budget_total=ticket_estimate,
        budget_scope="仅门票估算；交通和餐饮未计入",
        preferences=list(requirement.get("interests") or []),
    )
    db.add(itinerary)
    db.flush()
    for day_number in range(1, days + 1):
        day_attractions = day_selections[day_number - 1]
        day_title = f"第{day_number}天 · {city.name}探索" if day_attractions else f"第{day_number}天 · 自由安排"
        day = ItineraryDay(itinerary_id=itinerary.id, day_number=day_number, title=day_title)
        db.add(day)
        db.flush()
        cursor = datetime(2000, 1, 1, 9, 0)
        for attraction in day_attractions:
            end = cursor + timedelta(minutes=attraction.duration_minutes)
            db.add(ItineraryStop(
                day_id=day.id,
                attraction_id=attraction.id,
                name=attraction.name,
                start_time=cursor.strftime("%H:%M"),
                end_time=end.strftime("%H:%M"),
                note=f"{attraction.area} · 建议游览{attraction.duration_minutes}分钟 · 开放时间{attraction.opening_hours}",
            ))
            cursor = end + timedelta(minutes=45)
    validation = {
        "algorithm_version": "rules-v0.2",
        "opening_hours": {"status": "unknown", "message": "日期未定，常规开放时间已展示，特殊日期需出发前复核"},
        "travel": {"status": "unknown", "message": "缺少可靠路线数据，交通耗时和费用未计入"},
        "daily_load": {
            "status": "passed" if len(selected) >= required_count else "partial",
            "message": "每天安排 2 个主要景点，游览时长不超过 10 小时" if len(selected) >= required_count else f"资料库当前有 {len(selected)} 个符合条件的景点，已均匀安排到 {days} 天；未填满的时段保留为自由安排",
        },
        "budget": {
            "status": "over_budget" if requested_budget is not None and ticket_estimate > int(requested_budget) else "partial",
            "message": f"门票估算 ¥{ticket_estimate}，超过填写预算 ¥{requested_budget}" if requested_budget is not None and ticket_estimate > int(requested_budget) else "仅计入门票费用",
            "included": ["tickets"],
            "not_included": ["local_transport", "meals", "hotel", "intercity_transport", "shopping"],
        },
    }
    db.add(ItineraryValidation(itinerary_id=itinerary.id, data=validation))
    db.commit()
    return itinerary


def _is_cancelled(db: Session, job: PlanningJob) -> bool:
    db.refresh(job)
    return job.status == "cancelled"


def _complete_message(db: Session, job: PlanningJob, response: str, payload: dict, event_type: str = "message") -> None:
    db.add(ChatMessage(session_id=job.session_id, role="assistant", content=response, payload=payload))
    job.status, job.stage = "completed", "delivered"
    db.commit()
    emit(db, job.session_id, event_type, {"content": response, **payload, "turn_id": str(job.id)})
    done_status = "awaiting_confirmation" if event_type == "plan_confirm" else "completed"
    emit(db, job.session_id, "done", {"turn_id": str(job.id), "status": done_status})


def _process_plan_job(db: Session, job: PlanningJob) -> None:
    confirmation = latest_confirmation(db, job.session_id)
    if not confirmation:
        raise ValueError("没有待确认的旅行需求")
    requirement = dict(confirmation.payload or {})
    for stage, message in [
        ("retrieving", "正在查询城市和景点数据"),
        ("planning", "正在安排每日路线"),
        ("checking", "正在检查时间、负荷和预算范围"),
    ]:
        if _is_cancelled(db, job):
            emit(db, job.session_id, "done", {"turn_id": str(job.id), "status": "cancelled"})
            return
        job.stage = stage
        db.commit()
        emit(db, job.session_id, "stage", {"name": stage, "message": message, "turn_id": str(job.id)})
    itinerary = build_itinerary(db, job, requirement)
    if _is_cancelled(db, job):
        db.delete(itinerary)
        db.commit()
        emit(db, job.session_id, "done", {"turn_id": str(job.id), "status": "cancelled"})
        return
    response = generate_itinerary_summary(requirement, itinerary_dict(db, itinerary.id) or {}) or (
        f"已经生成 {requirement['destination']}{requirement['days']}日行程。常规开放时间已展示；日期、交通和未计入费用仍需确认。"
    )
    payload = {
        "type": "itinerary",
        "itinerary_id": itinerary.id,
        "city": requirement["destination"],
        "days": requirement["days"],
        "interests": requirement.get("interests", []),
    }
    job.result_itinerary_id = itinerary.id
    _complete_message(db, job, response, payload, "itinerary")


def process_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(PlanningJob, job_id)
        if not job or job.status != "queued":
            return
        is_plan_job = job.stage == "plan_queued"
        claimed = db.execute(update(PlanningJob).where(PlanningJob.id == job_id, PlanningJob.status == "queued").values(status="running", stage="understanding")).rowcount
        db.commit()
        if claimed != 1:
            return
        db.refresh(job)
        if is_plan_job:
            _process_plan_job(db, job)
            return

        emit(db, job.session_id, "stage", {"name": "extract", "message": "正在整理你的旅行需求", "turn_id": str(job.id)})
        session = db.get(ChatSession, job.session_id)
        session_messages = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == job.session_id).order_by(ChatMessage.id)))
        user_texts = [message.content for message in session_messages if message.role == "user"]
        user_text = user_texts[-1] if user_texts else ""
        city, _, _ = extract_request(user_text, db, user_texts[:-1])
        normalized_text = user_text.strip()
        profile = get_user_profile(db, session.user_id)
        added_preferences = update_user_profile(db, profile, normalized_text)
        profile_data = profile_payload(profile)
        name = profile.display_name

        if any(phrase in normalized_text for phrase in ["你是谁", "你是做什么的", "你能做什么"]):
            _complete_message(db, job, "我是行旅规划助手。我们可以先聊旅行偏好；只有你明确提出规划并确认需求后，我才会生成行程。", {"type": "chat", "profile": profile_data})
            return
        if "我是谁" in normalized_text:
            preferences = "、".join(profile.preferences or [])
            response = f"你是{name}。" if name else "目前我还不知道该怎么称呼你。"
            if preferences:
                response += f"我还记得你喜欢{preferences}。"
            response += "这些信息会用于之后的旅行推荐。"
            _complete_message(db, job, response, {"type": "chat", "profile": profile_data})
            return

        previous_assistant = next((message for message in reversed(session_messages[:-1]) if message.role == "assistant"), None)
        continuing_plan = bool(previous_assistant and (previous_assistant.payload or {}).get("planning_collect"))
        planning_requested = is_planning_request(user_text) or continuing_plan

        if not planning_requested and city:
            _complete_message(db, job, city_recommendation(city, db), {"type": "city_recommendation", "city": city.name})
            return

        if not planning_requested:
            llm_messages = [{"role": message.role, "content": message.content} for message in session_messages]
            response = generate_chat_reply(llm_messages, profile_data) or local_chat_response(normalized_text, profile, added_preferences)
            _complete_message(db, job, response, {"type": "chat", "profile": profile_data})
            return

        combined = " ".join(user_texts)
        day_match = re.search(r"(\d+)\s*[天日]", combined)
        planning_interests = list(dict.fromkeys([
            *[tag for tag in ["美食", "历史", "文化", "自然", "休闲", "亲子", "夜景", "购物"] if tag in combined],
            *[item for item in (profile.preferences or []) if item not in ["轻松慢游", "紧凑打卡"]],
        ]))
        has_pace = any(word in combined for word in ["慢节奏", "轻松", "悠闲", "休闲", "紧凑", "特种兵", "多安排", "打卡"]) or any(
            item in (profile.preferences or []) for item in ["轻松慢游", "紧凑打卡"]
        )
        clarify_payload = {"type": "clarify", "planning_collect": True, "profile": profile_data}
        if not city:
            _complete_message(db, job, "可以，我会先收集需求，不会直接生成行程。你想去哪个城市？目前完整支持北京、上海和成都。", clarify_payload, "clarify")
            return
        if not day_match:
            _complete_message(db, job, f"你准备在{city.name}玩几天？目前支持 2 到 5 天。", {**clarify_payload, "city": city.name}, "clarify")
            return
        if not planning_interests:
            _complete_message(db, job, "这次旅行你更偏好美食、历史文化、自然风景、拍照，还是其他体验？", {**clarify_payload, "city": city.name}, "clarify")
            return
        if not has_pace:
            _complete_message(db, job, f"我已经记下你喜欢{'、'.join(planning_interests)}。这次想轻松慢游，还是紧凑地多去几个地方？", {**clarify_payload, "city": city.name}, "clarify")
            return

        requirement = extract_plan_request(user_text, db, user_texts[:-1], list(profile.preferences or []), list(profile.avoid_places or []))
        payload = {"type": "plan_confirm", **requirement}
        _complete_message(db, job, confirmation_message(requirement), payload, "plan_confirm")
    except Exception as exc:
        db.rollback()
        job = db.get(PlanningJob, job_id)
        if job and job.status != "cancelled":
            job.status, job.stage, job.error_message = "failed", "failed", str(exc)
            db.commit()
            code = "NO_FEASIBLE_PLAN" if isinstance(exc, ValueError) else "INTERNAL"
            message = str(exc) if isinstance(exc, ValueError) else "规划暂时失败，请稍后重试"
            emit(db, job.session_id, "error", {"code": code, "message": message, "turn_id": str(job.id)})
            emit(db, job.session_id, "done", {"turn_id": str(job.id), "status": "failed"})
    finally:
        db.close()


async def process_job_async(job_id: int) -> None:
    await asyncio.to_thread(process_job, job_id)


def itinerary_dict(db: Session, itinerary_id: int) -> dict | None:
    itinerary = db.scalar(select(Itinerary).options(selectinload(Itinerary.itinerary_days).selectinload(ItineraryDay.stops)).where(Itinerary.id == itinerary_id))
    if not itinerary:
        return None
    validation = db.scalar(select(ItineraryValidation).where(ItineraryValidation.itinerary_id == itinerary_id))
    return {
        "id": itinerary.id, "title": itinerary.title, "city_name": itinerary.city_name, "days": itinerary.days,
        "status": itinerary.status, "budget_total": itinerary.budget_total, "budget_scope": itinerary.budget_scope, "preferences": list(itinerary.preferences or []), "lock_version": itinerary.lock_version,
        "validation": validation.data if validation else None,
        "itinerary_days": [{"day_number": day.day_number, "title": day.title, "stops": [{"id": stop.id, "attraction_id": stop.attraction_id, "name": stop.name, "start_time": stop.start_time, "end_time": stop.end_time, "note": stop.note} for stop in day.stops]} for day in itinerary.itinerary_days],
    }
