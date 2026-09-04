import asyncio
import json
import hashlib
import math
import re
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.db import SessionLocal
from app.llm import generate_chat_reply, generate_itinerary_summary
from app.maps import parse_coordinate, request_amap_geocode, request_amap_nearby_food, request_amap_route, request_amap_weather
from app.media import search_amap_place
from app.models import AgentEvent, AgentRun, AgentToolCall, Attraction, ChatMessage, ChatSession, City, IntercityRouteCache, Itinerary, ItineraryDay, ItineraryStop, ItineraryValidation, KnowledgeChunk, KnowledgeDocument, PlanningJob, RetrievalHit, RetrievalRun, RouteCache, UserProfile


CITY_NAMES = {"北京": "北京", "上海": "上海", "成都": "成都", "北京市": "北京", "上海市": "上海", "成都市": "成都", "蓉城": "成都"}
CITY_CODES = {"北京": "010", "上海": "021", "成都": "028"}
CITY_ROUTE_COORDINATES = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "成都": (30.5728, 104.0668),
}
MEAL_ESTIMATE_PER_PERSON_DAY = 120
HOTEL_ESTIMATE_PER_ROOM_NIGHT = 350
DRIVING_FUEL_ESTIMATE_PER_KM = 0.65
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

KNOWLEDGE_EMBEDDING_MODEL = "local-hash-v1"
KNOWLEDGE_DIMENSIONS = 128


def split_knowledge_content(content: str, size: int = 420) -> list[str]:
    text = re.sub(r"\s+", " ", content).strip()
    return [text[index:index + size] for index in range(0, len(text), size) if text[index:index + size].strip()]


def local_embedding(text: str) -> list[float]:
    vector = [0.0] * KNOWLEDGE_DIMENSIONS
    normalized = re.sub(r"\s+", "", text.lower())
    grams = [normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))] or [normalized]
    for gram in grams:
        slot = int(hashlib.sha256(gram.encode("utf-8")).hexdigest()[:8], 16) % KNOWLEDGE_DIMENSIONS
        vector[slot] += 1.0
    length = math.sqrt(sum(value * value for value in vector))
    return [round(value / length, 8) for value in vector] if length else vector


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def rebuild_knowledge_chunks(db: Session, document: KnowledgeDocument) -> None:
    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete()
    for index, chunk in enumerate(split_knowledge_content(document.content)):
        db.add(KnowledgeChunk(document_id=document.id, chunk_index=index, content=chunk, embedding=local_embedding(chunk), embedding_model=KNOWLEDGE_EMBEDDING_MODEL, token_count=len(chunk)))


def search_guide_knowledge(db: Session, city_id: int, query: str, session_id: int | None = None, top_k: int = 3) -> list[dict]:
    query_vector = local_embedding(query)
    chunks = list(db.scalars(select(KnowledgeChunk).join(KnowledgeDocument).where(KnowledgeDocument.city_id == city_id, KnowledgeDocument.status == "approved")))
    ranked = sorted(((chunk, cosine_similarity(query_vector, chunk.embedding or [])) for chunk in chunks), key=lambda item: item[1], reverse=True)
    hits = [(chunk, score) for chunk, score in ranked[:top_k] if score >= 0.08]
    run = RetrievalRun(session_id=session_id, query=query[:1000], city_id=city_id, top_k=top_k)
    db.add(run)
    db.flush()
    results = []
    for rank, (chunk, score) in enumerate(hits, start=1):
        document = db.get(KnowledgeDocument, chunk.document_id)
        db.add(RetrievalHit(retrieval_run_id=run.id, chunk_id=chunk.id, rank=rank, score=score))
        results.append({"content": chunk.content, "title": document.title, "source_name": document.source_name, "source_url": document.source_url, "updated_at": document.updated_at.isoformat(), "score": round(score, 3)})
    db.flush()
    return results


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
        destination_match = re.search(r"(?:去|到)\s*(北京|上海|成都)(?:市)?", candidate_text)
        if destination_match:
            city = db.scalar(select(City).where(City.name == destination_match.group(1), City.is_active.is_(True)))
            if city:
                break
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
    origin_match = re.search(r"从\s*(北京|上海|成都)(?:市)?(?:出发|去|到)", combined)
    origin_city = db.scalar(select(City).where(City.name == origin_match.group(1), City.is_active.is_(True))) if origin_match else None
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
    attraction_count_match = re.search(r"(\d+)\s*(?:个|处|家)\s*(?:景点|旅游景点|地方)", combined)
    return {
        "origin_city_id": origin_city.id if origin_city else None,
        "origin": origin_city.name if origin_city else None,
        "destination_city_id": city.id if city else None,
        "destination": city.name if city else None,
        "days": days,
        "attraction_count": max(1, min(int(attraction_count_match.group(1)), 12)) if attraction_count_match else 3,
        "budget_total": int(budget_match.group(1)) if budget_match else None,
        "budget_scope": "将计算门票、景点间市内交通、餐饮和住宿；不含往返目的地交通和购物",
        "interests": interests,
        "avoid_places": list(saved_avoid_places),
        "pace": pace,
        "traveler_count": int(traveler_match.group(1)) if traveler_match else 1,
        "transport": "public_transport",
        "start_date": None,
        "missing_optional": [item for item in ["origin_city_id" if not origin_city else None, "start_date"] if item],
    }


def confirmation_message(requirement: dict) -> str:
    pace_name = {"relaxed": "轻松", "balanced": "适中", "packed": "紧凑"}.get(requirement["pace"], "适中")
    budget = f"，预算 ¥{requirement['budget_total']}" if requirement.get("budget_total") else ""
    interests = "、".join(requirement.get("interests") or [])
    origin = f"从{requirement['origin']}出发，" if requirement.get("origin") else ""
    attraction_count = requirement.get("attraction_count", 3)
    return f"已整理你的旅行需求：{origin}{requirement['destination']} {requirement['days']} 天，安排 {attraction_count} 个景点，{requirement['traveler_count']} 人，偏好 {interests}，{pace_name}节奏{budget}。确认前请补充出发城市、日期和交通方式；行程会先查计划日期天气，再查询景点坐标、驾车路线和附近美食。"


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


def parse_start_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def opening_window(attraction: Attraction, visit_date: date | None) -> tuple[int, int, str | None]:
    """Return opening minutes, closing minutes and a validation message for common source formats."""
    hours = attraction.opening_hours or ""
    if "全天开放" in hours:
        return 0, 24 * 60, None
    closed_weekdays = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    closed_match = re.search(r"周([一二三四五六日天])闭馆", hours)
    if visit_date and closed_match and visit_date.weekday() == closed_weekdays[closed_match.group(1)]:
        return 0, 0, f"{visit_date.isoformat()} 为{closed_match.group(0)}"
    window_match = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", hours)
    if not window_match:
        return 9 * 60, 18 * 60, "开放时间格式无法自动校验，需出发前确认"
    start_hour, start_minute, end_hour, end_minute = (int(item) for item in window_match.groups())
    return start_hour * 60 + start_minute, end_hour * 60 + end_minute, None


def _format_clock(minutes: int) -> str:
    normalized = max(0, min(minutes, 23 * 60 + 59))
    return f"{normalized // 60:02d}:{normalized % 60:02d}"


def _coordinates(attraction: Attraction) -> tuple[float, float] | None:
    if attraction.latitude is None or attraction.longitude is None:
        return None
    return attraction.latitude, attraction.longitude


def ensure_route_coordinates(db: Session, attractions: list[Attraction], city: City) -> tuple[str | None, list[int]]:
    """Resolve each attraction's text address before any route tool receives coordinates."""
    city_code = CITY_CODES.get(city.name)
    unresolved: list[int] = []
    for attraction in attractions:
        if _coordinates(attraction):
            continue
        geocoded = request_amap_geocode(f"{city.name}{attraction.name}")
        coordinate = geocoded.get("coordinate") if geocoded else None
        place = None
        if not coordinate:
            place = search_amap_place(attraction.name, city.name)
            coordinate = parse_coordinate(place.get("location")) if place else None
        if not coordinate:
            unresolved.append(attraction.id)
            continue
        attraction.latitude, attraction.longitude = coordinate
        city_code = city_code or (geocoded or {}).get("citycode") or (place or {}).get("citycode")
    db.flush()
    return city_code, unresolved


def _route_cache_key(origin: Attraction, destination: Attraction, transport: str, travel_date: date | None) -> tuple[int, int, str, str]:
    return origin.id, destination.id, transport, travel_date.isoformat() if transport == "public_transport" and travel_date else ""


def route_segment(
    db: Session,
    origin: Attraction,
    destination: Attraction,
    transport: str,
    city_code: str | None,
    travel_date: date | None,
) -> dict:
    origin_id, destination_id, mode, service_date = _route_cache_key(origin, destination, transport, travel_date)
    now = datetime.now()
    cached = db.scalar(select(RouteCache).where(
        RouteCache.origin_attraction_id == origin_id,
        RouteCache.destination_attraction_id == destination_id,
        RouteCache.transport == mode,
        RouteCache.service_date == service_date,
    ))
    if cached and cached.expires_at > now:
        return {**cached.route_data, "cached": True}
    origin_coordinate, destination_coordinate = _coordinates(origin), _coordinates(destination)
    if not origin_coordinate or not destination_coordinate:
        return {"status": "unknown", "reason": "景点坐标缺失", "cached": False}
    route = request_amap_route(
        origin_coordinate, destination_coordinate, mode, city_code=city_code, travel_date=travel_date,
    )
    fallback = None
    if route is None and mode == "public_transport":
        route = request_amap_route(
            origin_coordinate, destination_coordinate, "walking", city_code=city_code, travel_date=travel_date,
        )
        fallback = "未找到公共交通方案，改用高德步行路线"
    if route is None:
        return {"status": "unknown", "reason": "高德路线服务暂时不可用", "cached": False}
    if mode == "driving":
        fuel = round(route["distance_meters"] / 1000 * DRIVING_FUEL_ESTIMATE_PER_KM, 2)
        route["fuel_estimate"] = fuel
        route["cost_yuan"] = round(route["cost_yuan"] + fuel, 2)
        route["cost_source"] = f"{route['cost_source']} + 油费按 ¥{DRIVING_FUEL_ESTIMATE_PER_KM}/公里估算"
    data = {"status": "passed", **route, "cached": False}
    if fallback:
        data["fallback"] = fallback
    if cached:
        cached.route_data = {key: value for key, value in data.items() if key != "cached"}
        cached.expires_at = now + timedelta(hours=24)
    else:
        db.add(RouteCache(
            origin_attraction_id=origin_id,
            destination_attraction_id=destination_id,
            transport=mode,
            service_date=service_date,
            route_data={key: value for key, value in data.items() if key != "cached"},
            expires_at=now + timedelta(hours=24),
        ))
    db.flush()
    return data


def _with_driving_fuel(route: dict) -> dict:
    if route.get("transport") != "driving":
        return route
    fuel = round(int(route.get("distance_meters", 0)) / 1000 * DRIVING_FUEL_ESTIMATE_PER_KM, 2)
    return {
        **route,
        "fuel_estimate": fuel,
        "cost_yuan": round(float(route.get("cost_yuan", 0)) + fuel, 2),
        "cost_source": f"{route.get('cost_source', '道路费用')} + 油费按 ¥{DRIVING_FUEL_ESTIMATE_PER_KM}/公里估算",
        "cost_basis": "vehicle",
    }


def resolve_city_route_endpoint(city: City) -> dict | None:
    geocoded = request_amap_geocode(city.name)
    if geocoded:
        return {**geocoded, "source": "amap_geocode"}
    coordinate = CITY_ROUTE_COORDINATES.get(city.name)
    if coordinate:
        return {"coordinate": coordinate, "citycode": CITY_CODES.get(city.name), "source": "configured_city_center"}
    place = search_amap_place(city.name)
    coordinate = parse_coordinate(place.get("location")) if place else None
    if coordinate:
        return {"coordinate": coordinate, "citycode": place.get("citycode"), "source": "amap_poi"}
    return None


def intercity_route(
    db: Session,
    origin_city: City | None,
    destination_city: City,
    transport: str,
    travel_date: date | None,
) -> dict:
    """Plan one cross-city leg and cache the provider result for 24 hours."""
    if not origin_city:
        return {"status": "unknown", "reason": "未选择出发城市"}
    if origin_city.id == destination_city.id:
        return {"status": "not_required", "reason": "出发城市与目的地相同"}
    if transport == "walking":
        return {"status": "unsupported", "reason": "跨城行程不支持步行方式，请选择公共交通、打车或自驾"}
    if not travel_date:
        return {"status": "unknown", "reason": "未填写出发日期"}
    service_date = travel_date.isoformat()
    now = datetime.now()
    cached = db.scalar(select(IntercityRouteCache).where(
        IntercityRouteCache.origin_city_id == origin_city.id,
        IntercityRouteCache.destination_city_id == destination_city.id,
        IntercityRouteCache.transport == transport,
        IntercityRouteCache.service_date == service_date,
    ))
    if cached and cached.expires_at > now:
        return {**cached.route_data, "cached": True}
    origin = resolve_city_route_endpoint(origin_city)
    destination = resolve_city_route_endpoint(destination_city)
    if not origin or not destination:
        return {"status": "unknown", "reason": "无法解析出发城市或目的地坐标"}
    route = request_amap_route(
        origin["coordinate"], destination["coordinate"], transport,
        city_code=origin.get("citycode") or CITY_CODES.get(origin_city.name),
        destination_city_code=destination.get("citycode") or CITY_CODES.get(destination_city.name),
        travel_date=travel_date,
    )
    if not route:
        return {"status": "unknown", "reason": "高德未返回跨城路线"}
    data = {
        "status": "passed", "from_city": origin_city.name, "to_city": destination_city.name,
        "origin_coordinate_source": origin["source"], "destination_coordinate_source": destination["source"],
        **_with_driving_fuel(route), "cached": False,
    }
    if cached:
        cached.route_data = {key: value for key, value in data.items() if key != "cached"}
        cached.expires_at = now + timedelta(hours=24)
    else:
        db.add(IntercityRouteCache(
            origin_city_id=origin_city.id, destination_city_id=destination_city.id,
            transport=transport, service_date=service_date,
            route_data={key: value for key, value in data.items() if key != "cached"},
            expires_at=now + timedelta(hours=24),
        ))
    db.flush()
    return data


def route_cost_for_group(route: dict, people: int) -> float:
    amount = float(route.get("cost_yuan", 0))
    cost_basis = route.get("cost_basis") or ("per_person" if route.get("transport") == "public_transport" else "vehicle")
    return round(amount * people if cost_basis == "per_person" else amount, 2)


def order_day_attractions(attractions: list[Attraction]) -> list[Attraction]:
    """Keep the first ranked stop, then choose the nearest available stop by straight-line distance."""
    if len(attractions) < 3 or not all(_coordinates(item) for item in attractions):
        return attractions
    remaining = list(attractions[1:])
    ordered = [attractions[0]]
    while remaining:
        previous = _coordinates(ordered[-1])
        assert previous is not None
        next_item = min(remaining, key=lambda item: (previous[0] - _coordinates(item)[0]) ** 2 + (previous[1] - _coordinates(item)[1]) ** 2)
        ordered.append(next_item)
        remaining.remove(next_item)
    return ordered


def schedule_day(
    db: Session,
    attractions: list[Attraction],
    day_number: int,
    visit_date: date | None,
    transport: str,
    city_code: str | None,
) -> tuple[list[dict], list[dict], list[str]]:
    cursor = 9 * 60
    previous: Attraction | None = None
    scheduled: list[dict] = []
    segments: list[dict] = []
    opening_issues: list[str] = []
    for attraction in order_day_attractions(attractions):
        route = None
        if previous:
            route = route_segment(db, previous, attraction, transport, city_code, visit_date)
            segments.append({"from": previous.name, "to": attraction.name, **route})
            if route["status"] == "passed":
                cursor += max(1, (int(route["duration_seconds"]) + 59) // 60)
        opens_at, closes_at, opening_issue = opening_window(attraction, visit_date)
        if closes_at == 0:
            opening_issues.append(f"{attraction.name}：{opening_issue}")
        elif opening_issue:
            opening_issues.append(f"{attraction.name}：{opening_issue}")
        cursor = max(cursor, opens_at)
        end = cursor + attraction.duration_minutes
        if closes_at and end > closes_at:
            opening_issues.append(f"{attraction.name}：预计 {_format_clock(end)} 结束，晚于 {attraction.opening_hours}")
        note = f"{attraction.area} · 建议游览{attraction.duration_minutes}分钟 · 开放时间{attraction.opening_hours}"
        if route and route["status"] == "passed":
            note += f" · 距上一站 {route['distance_meters'] / 1000:.1f}公里，约 {max(1, round(route['duration_seconds'] / 60))}分钟"
        elif route:
            note += " · 上一站路线待确认"
        scheduled.append({"attraction": attraction, "start_time": _format_clock(cursor), "end_time": _format_clock(end), "note": note})
        cursor = end
        previous = attraction
    return scheduled, segments, opening_issues


def estimate_budget(
    attractions: list[Attraction],
    days: int,
    people: int,
    requested_budget: int | None,
    segments: list[dict],
    intercity_routes: list[dict] | None = None,
) -> dict:
    ticket_estimate = sum(item.ticket_price for item in attractions) * people
    transport_estimate = round(sum(route_cost_for_group(segment, people) for segment in segments if segment.get("status") == "passed"), 2)
    intercity_routes = intercity_routes or []
    intercity_transport_estimate = round(sum(route_cost_for_group(route, people) for route in intercity_routes if route.get("status") == "passed"), 2)
    routed_distance = sum(int(segment.get("distance_meters", 0)) for segment in segments if segment.get("status") == "passed")
    meal_estimate = MEAL_ESTIMATE_PER_PERSON_DAY * people * days
    hotel_rooms = max(1, (people + 1) // 2)
    hotel_estimate = HOTEL_ESTIMATE_PER_ROOM_NIGHT * hotel_rooms * max(0, days - 1)
    total_estimate = round(ticket_estimate + transport_estimate + intercity_transport_estimate + meal_estimate + hotel_estimate, 2)
    intercity_complete = bool(intercity_routes) and all(route.get("status") in {"passed", "not_required"} for route in intercity_routes)
    return {
        "ticket_estimate": ticket_estimate,
        "local_transport_estimate": transport_estimate,
        "intercity_transport_estimate": intercity_transport_estimate,
        "meal_estimate": meal_estimate,
        "hotel_estimate": hotel_estimate,
        "total_estimate": total_estimate,
        "days": days,
        "people": people,
        "hotel_rooms": hotel_rooms,
        "requested_budget": requested_budget,
        "within_budget": requested_budget is None or total_estimate <= requested_budget,
        "routed_distance_meters": routed_distance,
        "scope": ["tickets", "local_transport_between_attractions", "meals", "hotel", *( ["intercity_round_trip"] if intercity_complete else [] )],
        "not_included": [*( ["intercity_transport"] if not intercity_complete else [] ), "shopping"],
        "assumptions": {
            "meal_per_person_day": MEAL_ESTIMATE_PER_PERSON_DAY,
            "hotel_per_room_night": HOTEL_ESTIMATE_PER_ROOM_NIGHT,
            "hotel_occupancy": "2人/间",
            "driving_fuel_per_km": DRIVING_FUEL_ESTIMATE_PER_KM,
        },
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
    start_date = parse_start_date(requirement.get("start_date"))
    weather = request_amap_weather(CITY_CODES.get(city.name), start_date)
    if agent_run:
        record_tool_call(db, agent_run, "query_weather", {"city": city.name, "travel_date": start_date.isoformat() if start_date else None}, weather)
    _emit_agent_stage(db, job, "retrieving", "正在查询景点资料")
    ranked = search_attractions(db, city, interest_tags, avoid_places)
    required_count = max(1, min(int(requirement.get("attraction_count", 3)), 12))
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
    initial_ticket_estimate = sum(item.ticket_price for item in initial_selected) * traveler_count
    selected, repaired_for_budget = select_with_budget(ranked, required_count, traveler_count, requested_budget)
    repair_attempts = 1 if repaired_for_budget else 0
    if agent_run and repaired_for_budget:
        record_tool_call(db, agent_run, "repair_plan", {
            "attempt": repair_attempts, "max_attempts": 2, "failed_constraint": "ticket_budget", "before_ticket_estimate": initial_ticket_estimate,
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
    _emit_agent_stage(db, job, "planning", "正在补齐景点坐标并调用高德规划路线")
    if agent_run:
        for attraction in selected:
            detail = get_attraction_detail(db, attraction.id, city.id)
            record_tool_call(db, agent_run, "get_attraction_detail", {"attraction_id": attraction.id}, _attraction_data(detail))
    transport = requirement.get("transport") or "public_transport"
    origin_city = db.get(City, requirement.get("origin_city_id")) if requirement.get("origin_city_id") else None
    intercity_routes: list[dict] = []
    if origin_city and origin_city.id == city.id:
        intercity_routes.append({"status": "not_required", "reason": "出发城市与目的地相同", "from_city": city.name, "to_city": city.name})
    elif origin_city:
        intercity_routes = [
            intercity_route(db, origin_city, city, transport, start_date),
            intercity_route(db, city, origin_city, transport, start_date + timedelta(days=days - 1) if start_date else None),
        ]
    else:
        intercity_routes.append({"status": "unknown", "reason": "未选择出发城市"})
    if agent_run:
        record_tool_call(db, agent_run, "calculate_intercity_routes", {
            "origin_city": origin_city.name if origin_city else None,
            "destination_city": city.name,
            "transport": transport,
            "outbound_date": start_date.isoformat() if start_date else None,
            "return_date": (start_date + timedelta(days=days - 1)).isoformat() if start_date else None,
        }, {"routes": intercity_routes})
    city_code, unresolved_attraction_ids = ensure_route_coordinates(db, selected, city)
    if agent_run:
        record_tool_call(db, agent_run, "resolve_attraction_coordinates", {
            "city": city.name, "attraction_ids": [item.id for item in selected],
        }, {
            "city_code": city_code, "unresolved_attraction_ids": unresolved_attraction_ids,
            "resolved_count": len(selected) - len(unresolved_attraction_ids),
        })
    navigation_stops = order_day_attractions(selected)
    driving_segments = [
        {"from": origin.name, "to": destination.name, **route_segment(db, origin, destination, "driving", city_code, start_date)}
        for origin, destination in zip(navigation_stops, navigation_stops[1:])
    ]
    nearby_food = [
        {"attraction_id": attraction.id, "attraction_name": attraction.name, "items": request_amap_nearby_food(_coordinates(attraction), city.name, limit=2)}
        for attraction in navigation_stops
        if _coordinates(attraction)
    ]
    if agent_run:
        record_tool_call(db, agent_run, "calculate_driving_navigation", {
            "ordered_attraction_ids": [item.id for item in navigation_stops],
            "coordinate_ready": not unresolved_attraction_ids,
        }, {"segments": driving_segments})
        record_tool_call(db, agent_run, "search_nearby_food", {
            "attraction_ids": [item.id for item in navigation_stops], "radius_meters": 1500,
        }, {"recommendations": nearby_food})
    day_selections: list[list[Attraction]] = [[] for _ in range(days)]
    per_day = max(1, (len(selected) + days - 1) // days)
    for index, attraction in enumerate(selected):
        day_selections[min(index // per_day, days - 1)].append(attraction)
    day_plans: list[list[dict]] = []
    segments: list[dict] = []
    opening_issues: list[str] = []
    for day_number, day_attractions in enumerate(day_selections, start=1):
        visit_date = start_date + timedelta(days=day_number - 1) if start_date else None
        scheduled, day_segments, day_opening_issues = schedule_day(
            db, day_attractions, day_number, visit_date, transport, city_code,
        )
        day_plans.append(scheduled)
        segments.extend(day_segments)
        opening_issues.extend(day_opening_issues)
    budget = estimate_budget(selected, days, traveler_count, requested_budget, segments, intercity_routes)
    if agent_run:
        record_tool_call(db, agent_run, "calculate_amap_routes", {
            "transport": transport, "start_date": start_date.isoformat() if start_date else None,
        }, {"segments": segments, "unresolved_attraction_ids": unresolved_attraction_ids})
        record_tool_call(db, agent_run, "estimate_budget", {
            "attraction_ids": [item.id for item in selected], "days": days, "people": traveler_count,
        }, budget)
    _emit_agent_stage(db, job, "checking", "正在校验营业时间、路线耗时和完整预算")
    _emit_agent_stage(db, job, "saving", "正在保存可执行行程")
    itinerary = Itinerary(
        user_id=db.scalar(select(ChatSession.user_id).where(ChatSession.id == job.session_id)),
        session_id=job.session_id,
        title=f"{city.name}{days}日个性行程",
        city_name=city.name,
        days=days,
        budget_total=round(budget["total_estimate"]),
        budget_scope=(
            "往返跨城交通、门票、景点间市内交通、餐饮和住宿估算；不含购物"
            if "intercity_round_trip" in budget["scope"] else
            "门票、景点间市内交通、餐饮和住宿估算；未覆盖跨城交通和购物"
        ),
        preferences=list(requirement.get("interests") or []),
    )
    db.add(itinerary)
    db.flush()
    for day_number in range(1, days + 1):
        day_attractions = day_plans[day_number - 1]
        day_title = f"第{day_number}天 · {city.name}探索" if day_attractions else f"第{day_number}天 · 自由安排"
        day = ItineraryDay(itinerary_id=itinerary.id, day_number=day_number, title=day_title)
        db.add(day)
        db.flush()
        for scheduled in day_attractions:
            attraction = scheduled["attraction"]
            db.add(ItineraryStop(
                day_id=day.id,
                attraction_id=attraction.id,
                name=attraction.name,
                start_time=scheduled["start_time"],
                end_time=scheduled["end_time"],
                note=scheduled["note"],
            ))
    route_successes = [segment for segment in segments if segment.get("status") == "passed"]
    route_failures = [segment for segment in segments if segment.get("status") != "passed"]
    travel_status = "passed" if segments and not route_failures else "partial"
    intercity_successes = [route for route in intercity_routes if route.get("status") == "passed"]
    intercity_status = "passed" if intercity_routes and all(route.get("status") in {"passed", "not_required"} for route in intercity_routes) else "partial"
    intercity_date_fallback = any(route.get("schedule_date_fallback") for route in intercity_successes)
    opening_failures = [issue for issue in opening_issues if "闭馆" in issue or "晚于" in issue]
    opening_status = "failed" if opening_failures else ("partial" if not start_date or opening_issues else "passed")
    daily_durations: list[int] = []
    for stops in day_plans:
        if stops:
            first = stops[0]["start_time"].split(":")
            last = stops[-1]["end_time"].split(":")
            daily_durations.append((int(last[0]) * 60 + int(last[1])) - (int(first[0]) * 60 + int(first[1])))
    budget_status = "over_budget" if requested_budget is not None and not budget["within_budget"] else ("passed" if requested_budget is not None else "partial")
    validation = {
        "algorithm_version": "amap-route-v2",
        "travel_start_date": start_date.isoformat() if start_date else None,
        "opening_hours": {
            "status": opening_status,
            "message": "已按出行日期校验营业时间" if opening_status == "passed" else (
                "存在闭馆或超出营业时间的安排：" + "；".join(opening_failures) if opening_failures else
                "未填写出行日期或部分开放时间无法自动解析，需出发前确认"
            ),
            "issues": opening_issues,
        },
        "weather": weather,
        "driving_navigation": {
            "status": "passed" if driving_segments and all(segment.get("status") == "passed" for segment in driving_segments) else "partial",
            "message": "已按景点文字地址转坐标后生成驾车导航路线" if driving_segments else "景点数量不足 2 个，未生成驾车导航路线",
            "segments": driving_segments,
        },
        "nearby_food": nearby_food,
        "travel": {
            "status": travel_status,
            "provider": "高德地图",
            "transport": transport,
            "message": f"已获取 {len(route_successes)} 段景点间路线" if travel_status == "passed" else "部分路线缺失或当天仅有一个景点，未计入的路段需确认",
            "total_distance_meters": budget["routed_distance_meters"],
            "total_duration_seconds": sum(int(segment.get("duration_seconds", 0)) for segment in route_successes),
            "total_cost": budget["local_transport_estimate"],
            "segments": segments,
            "unresolved_attraction_ids": unresolved_attraction_ids,
        },
        "intercity_travel": {
            "status": intercity_status,
            "provider": "高德地图",
            "transport": transport,
            "origin_city": origin_city.name if origin_city else None,
            "destination_city": city.name,
            "message": (
                "指定日期未返回跨城公共交通方案，已使用高德通用公共交通路线估算，车次需出发前确认"
                if intercity_status == "passed" and intercity_date_fallback else
                "已获取往返跨城路线" if intercity_status == "passed" else "跨城路线未完整获取，未返回费用不会计入预算"
            ),
            "total_distance_meters": sum(int(route.get("distance_meters", 0)) for route in intercity_successes),
            "total_duration_seconds": sum(int(route.get("duration_seconds", 0)) for route in intercity_successes),
            "total_cost": budget["intercity_transport_estimate"],
            "routes": intercity_routes,
        },
        "daily_load": {
            "status": "passed" if len(selected) >= required_count and all(duration <= 600 for duration in daily_durations) else "partial",
            "message": "每日安排已结合实际路线耗时，单日不超过 10 小时" if daily_durations and all(duration <= 600 for duration in daily_durations) else "部分日期未排满或安排时长超过建议范围，保留为自由安排",
            "durations_minutes": daily_durations,
        },
        "budget": {
            "status": budget_status,
            "message": (
                f"完整预算估算 ¥{budget['total_estimate']}，在填写预算 ¥{requested_budget} 内。" if budget_status == "passed" else
                f"完整预算估算 ¥{budget['total_estimate']}，超过填写预算 ¥{requested_budget}。" if budget_status == "over_budget" else
                f"完整预算估算 ¥{budget['total_estimate']}；未填写总预算，无法判断是否超支。"
            ),
            "included": budget["scope"],
            "not_included": budget["not_included"],
            "breakdown": {
                "tickets": budget["ticket_estimate"], "local_transport": budget["local_transport_estimate"],
                "intercity_transport": budget["intercity_transport_estimate"], "meals": budget["meal_estimate"],
                "hotel": budget["hotel_estimate"], "total": budget["total_estimate"],
            },
            "assumptions": budget["assumptions"],
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
            "start_date": start_date.isoformat() if start_date else None, "duration_limit_minutes": 600,
        }, {"opening_hours": validation["opening_hours"], "daily_load": validation["daily_load"]})
        record_tool_call(db, agent_run, "validate_plan", {
            "itinerary_id": itinerary.id, "selected_count": len(selected), "days": days,
        }, {
            "daily_load": validation["daily_load"], "budget": validation["budget"],
            "opening_hours": validation["opening_hours"], "travel": validation["travel"],
            "intercity_travel": validation["intercity_travel"],
        })
        record_tool_call(db, agent_run, "save_itinerary_draft", {
            "city": city.name, "days": days, "stop_ids": [item.id for item in selected],
        }, {"itinerary_id": itinerary.id})
        agent_run.itinerary_id = itinerary.id
        agent_run.status = "completed"
        agent_run.algorithm_version = "amap-route-v2"
        agent_run.summary = {
            "selected_count": len(selected), "requested_stop_count": required_count,
            "budget_repair_applied": repaired_for_budget, "repair_attempts": repair_attempts,
            "budget_total_estimate": budget["total_estimate"],
            "routed_segment_count": len(route_successes),
            "intercity_routed_segment_count": len(intercity_successes),
            "weather_status": weather.get("status"),
            "driving_navigation_segment_count": len(driving_segments),
            "nearby_food_count": sum(len(group["items"]) for group in nearby_food),
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
        f"已经生成 {requirement['destination']}{requirement['days']}日行程。已按所选交通方式计算景点间路线，并纳入门票、餐饮和住宿估算；往返目的地交通和购物未计入。"
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
