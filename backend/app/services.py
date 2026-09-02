import asyncio
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal
from app.llm import generate_chat_reply, generate_itinerary_summary
from app.models import AgentEvent, AgentRun, AgentToolCall, Attraction, ChatMessage, ChatSession, City, Itinerary, ItineraryDay, ItineraryStop, ItineraryValidation, PlanningJob, UserProfile


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
    attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city.id, Attraction.is_active.is_(True)).order_by(Attraction.id).limit(4)))
    highlights = "；".join(f"{item.name}（{item.description}）" for item in attractions)
    return f"{city.name}很适合城市漫游。第一次去可以先看看：{highlights}\n\n如果你想进一步规划，可以直接告诉我“帮我规划”，我会先收集条件并请你确认。"


def is_city_overview_request(text: str) -> bool:
    """Only use the fixed overview for an initial destination introduction, never for a follow-up."""
    followup_terms = ["美食", "好吃", "吃什么", "小吃", "餐厅", "火锅", "串串", "什么时候", "什么时间", "几月", "季节", "天气", "住哪里", "交通"]
    return not any(term in text for term in followup_terms) and any(phrase in text for phrase in ["我想去", "想去", "第一次去", "有什么景点", "推荐景点", "城市介绍"])


def city_followup_response(text: str, city: City, db: Session) -> str | None:
    """Useful local fallback when the dialogue model is unavailable."""
    if any(word in text for word in ["美食", "吃什么", "小吃", "餐厅", "火锅", "串串"]):
        food_spots = [item for item in db.scalars(select(Attraction).where(Attraction.city_id == city.id, Attraction.is_active.is_(True)).order_by(Attraction.id)) if "美食" in (item.tags or [])]
        spot_text = "、".join(item.name for item in food_spots[:2])
        return f"{city.name}可以先尝试火锅、串串香、担担面、钟水饺、龙抄手和甜水面。想边逛边吃的话，可把{spot_text or '当地老街区'}安排在同一段行程；点餐时可先说明自己能接受的辣度。"
    if any(word in text for word in ["什么时候", "什么时间", "几月", "季节", "天气"]):
        return f"{city.name}{city.season}。如果想以街巷漫游和美食为主，优先选择天气舒适的春秋；夏天可把户外安排放在早晚，并考虑周边避暑。"
    return None


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


def local_chat_response(text: str, profile: UserProfile, added_preferences: list[str], city: City | None = None, db: Session | None = None) -> str:
    name = profile.display_name
    if extract_name(text):
        return f"记住了，我会称呼你为{name}。你也可以继续告诉我平时喜欢的旅行方式、食物或不想去的地方。"
    if city and db:
        city_reply = city_followup_response(text, city, db)
        if city_reply:
            return city_reply
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
                city = db.scalar(select(City).where(City.name == normalized, City.is_active.is_(True)))
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


def start_agent_run(db: Session, job: PlanningJob, requirement: dict) -> AgentRun:
    run = AgentRun(job_id=job.id, input_data=requirement)
    db.add(run)
    db.flush()
    return run


def record_tool_call(db: Session, run: AgentRun, tool_name: str, input_data: dict, output_data: dict) -> None:
    sequence = db.scalar(select(AgentToolCall.sequence).where(AgentToolCall.agent_run_id == run.id).order_by(AgentToolCall.sequence.desc())) or 0
    db.add(AgentToolCall(
        agent_run_id=run.id,
        sequence=sequence + 1,
        tool_name=tool_name,
        input_data=input_data,
        output_data=output_data,
    ))
    db.flush()


def expanded_interest_tags(interests: list[str]) -> set[str]:
    tags = set(interests)
    if "摄影" in tags:
        tags.update(["文化", "自然", "夜景", "休闲"])
    if "辣味美食" in tags:
        tags.add("美食")
    if "历史文化" in tags:
        tags.update(["历史", "文化"])
    if "自然风景" in tags:
        tags.add("自然")
    return tags


def ranked_attractions_for_plan(db: Session, city: City, interest_tags: set[str], avoid_places: list[str]) -> list[tuple[Attraction, int]]:
    attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city.id, Attraction.is_active.is_(True)).order_by(Attraction.id)))
    available = [item for item in attractions if not any(avoid and avoid in item.name for avoid in avoid_places)]
    return sorted(
        [(item, sum(tag in interest_tags for tag in (item.tags or []))) for item in available],
        key=lambda item: (item[1], -item[0].ticket_price, -item[0].id),
        reverse=True,
    )


def select_with_budget(ranked: list[tuple[Attraction, int]], required_count: int, traveler_count: int, requested_budget: int | None) -> tuple[list[Attraction], bool]:
    preferred = [item for item, _ in ranked[:required_count]]
    if requested_budget is None or sum(item.ticket_price for item in preferred) * traveler_count <= requested_budget:
        return preferred, False

    # When the ideal plan exceeds a stated ticket budget, keep the cheapest relevant stops first.
    affordable: list[Attraction] = []
    total = 0
    for attraction, _ in sorted(ranked, key=lambda item: (item[0].ticket_price, -item[1], item[0].id)):
        cost = attraction.ticket_price * traveler_count
        if total + cost <= requested_budget:
            affordable.append(attraction)
            total += cost
    return affordable, True


def _attraction_data(attraction: Attraction, match_score: int | None = None) -> dict:
    data = {
        "id": attraction.id, "name": attraction.name, "city_id": attraction.city_id,
        "ticket_price": attraction.ticket_price, "duration_minutes": attraction.duration_minutes,
        "opening_hours": attraction.opening_hours, "area": attraction.area, "tags": attraction.tags or [],
    }
    if match_score is not None:
        data["match_score"] = match_score
    return data


def search_attractions(db: Session, city: City, interests: set[str], avoid_places: list[str]) -> list[tuple[Attraction, int]]:
    """Controlled lookup: candidates only originate from the selected city."""
    return ranked_attractions_for_plan(db, city, interests, avoid_places)


def get_attraction_detail(db: Session, attraction_id: int, city_id: int) -> Attraction:
    attraction = db.get(Attraction, attraction_id)
    if not attraction or not attraction.is_active or attraction.city_id != city_id:
        raise ValueError("景点不属于当前规划城市")
    return attraction


def estimate_budget(attractions: list[Attraction], days: int, people: int, budget: int | None) -> dict:
    ticket_estimate = sum(item.ticket_price for item in attractions) * people
    return {
        "ticket_estimate": ticket_estimate, "days": days, "people": people,
        "requested_budget": budget, "within_budget": budget is None or ticket_estimate <= budget,
        "scope": ["tickets"],
    }


def calculate_route_or_area_order(stops: list[Attraction]) -> tuple[list[Attraction], dict]:
    """Transparent area grouping until a real route provider is introduced."""
    ordered = sorted(stops, key=lambda item: ((item.area or "未分区"), item.id))
    return ordered, {
        "strategy": "area_grouping", "ordered_stop_ids": [item.id for item in ordered],
        "areas": [item.area for item in ordered],
    }


def validate_schedule(stops: list[Attraction], day_selections: list[list[Attraction]], city_id: int, required_count: int) -> dict:
    overlong_days = []
    for number, day_stops in enumerate(day_selections, start=1):
        duration = sum(item.duration_minutes for item in day_stops) + max(0, len(day_stops) - 1) * 45
        if duration > 600:
            overlong_days.append(number)
    invalid_city_ids = [item.id for item in stops if item.city_id != city_id]
    return {
        "opening_hours": {"status": "unknown", "message": "缺少出行日期和可解析的营业日规则，需在出发前确认。"},
        "daily_load": {
            "status": "failed" if overlong_days else ("passed" if len(stops) >= required_count else "partial"),
            "message": "单日游览时长未超过 10 小时。" if not overlong_days else f"第 {','.join(map(str, overlong_days))} 天超过 10 小时。",
        },
        "city": {"status": "passed" if not invalid_city_ids else "failed", "invalid_stop_ids": invalid_city_ids},
        "travel": {"status": "partial", "message": "已按区域排序；未接入真实交通路由，路程时间和费用不计入。"},
    }


def _emit_agent_stage(db: Session, job: PlanningJob, name: str, message: str) -> None:
    if _is_cancelled(db, job):
        raise ValueError("规划任务已取消")
    job.stage = name
    db.commit()
    emit(db, job.session_id, "stage", {"name": name, "message": message, "turn_id": str(job.id)})


def build_itinerary(db: Session, job: PlanningJob, requirement: dict, agent_run: AgentRun | None = None) -> Itinerary:
    city = db.get(City, requirement.get("destination_city_id"))
    if not city or not city.is_active or city.support_level != "full" or not city.planning_enabled:
        raise ValueError("当前目的地暂不支持完整行程规划")
    days = max(2, min(int(requirement.get("days", 3)), 5))
    interests = requirement.get("interests") or ["文化", "美食"]
    interest_tags = expanded_interest_tags(interests)
    avoid_places = requirement.get("avoid_places") or []
    _emit_agent_stage(db, job, "retrieving", "正在查询景点资料")
    ranked = search_attractions(db, city, interest_tags, avoid_places)
    required_count = days * 2
    if not ranked:
        raise ValueError(f"{city.name}当前没有符合排除条件的可用景点，请调整不想去的地方后重试")
    if agent_run:
        record_tool_call(db, agent_run, "search_attractions", {
            "city": city.name, "interests": sorted(interest_tags), "budget": requirement.get("budget_total"), "avoid_places": avoid_places,
        }, {
            "candidate_count": len(ranked),
            "candidates": [_attraction_data(item, score) for item, score in ranked],
        })
    traveler_count = max(1, int(requirement.get("traveler_count", 1)))
    requested_budget = requirement.get("budget_total")
    initial_selected = [item for item, _ in ranked[:required_count]]
    initial_budget = estimate_budget(initial_selected, days, traveler_count, requested_budget)
    selected, repaired_for_budget = select_with_budget(ranked, required_count, traveler_count, requested_budget)
    repair_attempts = 1 if repaired_for_budget else 0
    if agent_run and repaired_for_budget:
        record_tool_call(db, agent_run, "repair_plan", {
            "attempt": repair_attempts, "max_attempts": 2, "failed_constraint": "budget", "before": initial_budget,
        }, {
            "strategy": "keep_cheapest_relevant_stops", "after_stop_ids": [item.id for item in selected],
        })
    if agent_run:
        record_tool_call(db, agent_run, "select_stops", {
            "required_count": required_count, "traveler_count": traveler_count, "ticket_budget": requested_budget,
        }, {
            "selected_count": len(selected), "selected": [_attraction_data(item) for item in selected],
            "budget_repair_applied": repaired_for_budget,
        })
    _emit_agent_stage(db, job, "planning", "正在整理景点详情并安排同区域路线")
    if agent_run:
        for attraction in selected:
            detail = get_attraction_detail(db, attraction.id, city.id)
            record_tool_call(db, agent_run, "get_attraction_detail", {"attraction_id": attraction.id}, _attraction_data(detail))
    budget = estimate_budget(selected, days, traveler_count, requested_budget)
    selected, route = calculate_route_or_area_order(selected)
    if agent_run:
        record_tool_call(db, agent_run, "estimate_budget", {"attraction_ids": [item.id for item in selected], "days": days, "people": traveler_count}, budget)
        record_tool_call(db, agent_run, "calculate_route_or_area_order", {"stop_ids": [item.id for item in selected]}, route)
    day_selections: list[list[Attraction]] = [[] for _ in range(days)]
    per_day = max(1, (len(selected) + days - 1) // days)
    for index, attraction in enumerate(selected):
        day_selections[min(index // per_day, days - 1)].append(attraction)
    _emit_agent_stage(db, job, "checking", "正在校验时间、预算和城市归属")
    schedule_validation = validate_schedule(selected, day_selections, city.id, required_count)
    ticket_estimate = budget["ticket_estimate"]
    _emit_agent_stage(db, job, "saving", "正在保存可执行行程")
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
    validation = {
        "algorithm_version": "tool-agent-v2",
        **schedule_validation,
        "budget": {
            "status": "passed" if requested_budget is not None and budget["within_budget"] else "partial",
            "message": f"门票估算 ¥{ticket_estimate}，在填写预算内。" if requested_budget is not None and budget["within_budget"] else "仅计入门票费用。",
            "included": ["tickets"],
            "not_included": ["local_transport", "meals", "hotel", "intercity_transport", "shopping"],
        },
        "interest_match": {
            "status": "passed" if any(score > 0 for _, score in ranked[:len(selected)]) else "partial",
            "matched_tags": sorted(interest_tags),
        },
        "repair": {"attempts": repair_attempts, "max_attempts": 2, "applied": repaired_for_budget},
    }
    db.add(ItineraryValidation(itinerary_id=itinerary.id, data=validation))
    if agent_run:
        record_tool_call(db, agent_run, "validate_schedule", {
            "stop_ids": [item.id for item in selected], "opening_hours": [item.opening_hours for item in selected],
            "duration_limit_minutes": 600,
        }, schedule_validation)
        record_tool_call(db, agent_run, "validate_plan", {
            "itinerary_id": itinerary.id, "selected_count": len(selected), "days": days,
        }, {
            "daily_load": validation["daily_load"], "budget": validation["budget"],
            "opening_hours": validation["opening_hours"], "travel": validation["travel"],
        })
        record_tool_call(db, agent_run, "save_itinerary_draft", {
            "city": city.name, "days": days, "stop_ids": [item.id for item in selected],
        }, {"itinerary_id": itinerary.id})
        agent_run.itinerary_id = itinerary.id
        agent_run.status = "completed"
        agent_run.algorithm_version = "tool-agent-v2"
        agent_run.summary = {
            "selected_count": len(selected), "requested_stop_count": required_count,
            "budget_repair_applied": repaired_for_budget, "repair_attempts": repair_attempts,
            "ticket_estimate": ticket_estimate,
        }
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
    agent_run = start_agent_run(db, job, requirement)
    # The actual tool functions below own stage emission. Keep this compatibility loop inert.
    job.stage = "tool_execution"
    for stage, message in [
        ("retrieving", "正在查询城市和景点数据"),
        ("planning", "正在安排每日路线"),
        ("checking", "正在检查时间、负荷和预算范围"),
    ]:
        if job.stage == "tool_execution":
            break
        if _is_cancelled(db, job):
            emit(db, job.session_id, "done", {"turn_id": str(job.id), "status": "cancelled"})
            return
        job.stage = stage
        db.commit()
        emit(db, job.session_id, "stage", {"name": stage, "message": message, "turn_id": str(job.id)})
    itinerary = build_itinerary(db, job, requirement, agent_run)
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

        if not planning_requested and city and is_city_overview_request(normalized_text):
            _complete_message(db, job, city_recommendation(city, db), {"type": "city_recommendation", "city": city.name})
            return

        if not planning_requested:
            llm_messages = [{"role": message.role, "content": message.content} for message in session_messages]
            response = generate_chat_reply(llm_messages, profile_data) or local_chat_response(normalized_text, profile, added_preferences, city, db)
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
            agent_run = db.scalar(select(AgentRun).where(AgentRun.job_id == job.id))
            if agent_run:
                agent_run.status = "failed"
                agent_run.summary = {**(agent_run.summary or {}), "failure": {"code": type(exc).__name__, "message": str(exc)}}
            db.commit()
            code = "NO_FEASIBLE_PLAN" if isinstance(exc, ValueError) else "INTERNAL"
            message = str(exc) if isinstance(exc, ValueError) else "规划暂时失败，请稍后重试"
            # Do not use the reserved EventSource "error" event for an application failure.
            emit(db, job.session_id, "agent_error", {"code": code, "message": message, "turn_id": str(job.id)})
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
