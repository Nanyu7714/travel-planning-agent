import asyncio
import hmac
import json
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password, new_csrf_token, new_refresh_token, token_hash, verify_password
from app.db import Base, SessionLocal, engine, get_db
from app.llm import get_llm_status
from app.models import AgentEvent, Attraction, AuthSession, ChatMessage, ChatSession, City, Favorite, IdempotencyRecord, Itinerary, ItineraryDay, ItineraryFeedback, ItineraryRevision, ItineraryStop, ItineraryValidation, MediaAsset, PlanningJob, RecentView, ShareLink, User, UserProfile
from app.schemas import AccountDeleteIn, AdminFeedbackOut, AdminSessionOut, AdminUserOut, AdminUserUpdateIn, AttractionOut, AuthSessionOut, CityOut, EmailChangeIn, FeedbackIn, FeedbackOut, ItineraryRevisionOut, ItineraryUpdateIn, LoginIn, MediaAssetOut, MessageIn, MessageOut, PasswordChangeIn, PlanConfirmIn, RegisterIn, ReplanIn, SessionOut, SessionUpdateIn, ShareCreateIn, ShareOut, UserOut, UserProfileOut, UserProfileUpdateIn
from app.services import CITY_NAMES, confirmation_message, itinerary_dict, latest_confirmation, process_job_async


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_user_identity_columns()
    ensure_user_profile_columns()
    ensure_itinerary_columns()
    ensure_session_management_columns()
    seed_database()
    backfill_user_public_ids()
    backfill_session_titles()
    yield


app = FastAPI(title="行旅旅游规划 Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.app_base_url], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
MEDIA_ROOT = Path(__file__).resolve().parent.parent / "media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")


def ensure_user_identity_columns() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    timestamp_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    with engine.begin() as connection:
        if "public_id" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN public_id VARCHAR(4)"))
        if "deleted_at" not in columns:
            connection.execute(text(f"ALTER TABLE users ADD COLUMN deleted_at {timestamp_type}"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_public_id ON users (public_id)"))


def ensure_user_profile_columns() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("user_profiles")}
    with engine.begin() as connection:
        if "avoid_places" not in columns:
            connection.execute(text("ALTER TABLE user_profiles ADD COLUMN avoid_places JSON" if engine.dialect.name == "sqlite" else "ALTER TABLE user_profiles ADD COLUMN avoid_places JSONB"))
        empty_list = "'[]'" if engine.dialect.name == "sqlite" else "CAST('[]' AS JSONB)"
        connection.execute(text(f"UPDATE user_profiles SET avoid_places = {empty_list} WHERE avoid_places IS NULL"))


def ensure_itinerary_columns() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("itineraries")}
    with engine.begin() as connection:
        if "preferences" not in columns:
            connection.execute(text("ALTER TABLE itineraries ADD COLUMN preferences JSON" if engine.dialect.name == "sqlite" else "ALTER TABLE itineraries ADD COLUMN preferences JSONB"))


def allocate_public_id(db: Session) -> str:
    used_ids = set(db.scalars(select(User.public_id).where(User.public_id.is_not(None))))
    active_usernames = db.scalars(select(User.username).where(User.is_active.is_(True))).all()
    used_ids.update(username for username in active_usernames if re.fullmatch(r"\d{4}", username))
    if len(used_ids) >= 10_000:
        raise HTTPException(503, "用户 ID 已分配完毕，请联系管理员")
    start = secrets.randbelow(10_000)
    for offset in range(10_000):
        candidate = f"{(start + offset) % 10_000:04d}"
        if candidate not in used_ids:
            return candidate
    raise HTTPException(503, "用户 ID 已分配完毕，请联系管理员")


def backfill_user_public_ids() -> None:
    db = SessionLocal()
    try:
        users = db.scalars(select(User).where(User.is_active.is_(True), User.public_id.is_(None)).order_by(User.id)).all()
        for user in users:
            user.public_id = allocate_public_id(db)
            db.flush()
        db.commit()
    finally:
        db.close()


def ensure_session_management_columns() -> None:
    """Keep existing development databases compatible until formal migrations land."""
    columns = {column["name"] for column in inspect(engine).get_columns("chat_sessions")}
    timestamp_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"
    additions = {
        "is_pinned": "BOOLEAN NOT NULL DEFAULT false",
        "archived_at": timestamp_type,
        "deleted_at": timestamp_type,
        "updated_at": timestamp_type,
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE chat_sessions ADD COLUMN {name} {definition}"))


def seed_database() -> None:
    db = SessionLocal()
    try:
        if not db.scalar(select(User).where(User.username == "admin")):
            db.add(User(username="admin", email="admin@travel.local", password_hash=hash_password("123456"), role="admin"))
        if not db.scalar(select(City)):
            cities = [
                City(slug="beijing", name="北京", aliases=["北京市"], description="古都人文与现代城市交织，适合第一次深度认识中国北方。", season="春秋最佳，四季皆有看点", budget="¥300-600/天", recommended_days="3-5天", image_url="https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=1200&q=80"),
                City(slug="shanghai", name="上海", aliases=["上海市", "魔都"], description="沿江城市风景、建筑、人文展览和丰富的夜间生活。", season="春秋舒适，冬季适合城市漫游", budget="¥400-800/天", recommended_days="2-4天", image_url="https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=1200&q=80"),
                City(slug="chengdu", name="成都", aliases=["成都市", "蓉城"], description="把美食、茶馆、街巷和自然风光安排在从容的城市节奏里。", season="春秋宜人，夏季周边避暑", budget="¥300-600/天", recommended_days="3-5天", image_url="https://images.unsplash.com/photo-1548919973-5cef591cdbc9?auto=format&fit=crop&w=1200&q=80"),
            ]
            db.add_all(cities)
            db.flush()
            attractions = [
                (cities[0], "故宫博物院", "沿中轴线感受明清宫殿建筑与馆藏文物。", ["历史", "文化"], "08:30-17:00（周一闭馆）", 60, 180, "东城区"),
                (cities[0], "颐和园", "皇家园林与昆明湖山水相映，适合慢慢游览。", ["自然", "历史", "休闲"], "06:30-18:00", 30, 180, "海淀区"),
                (cities[0], "天坛公园", "古代祭祀建筑群与城市绿地，清晨氛围很好。", ["历史", "文化", "休闲"], "06:00-22:00", 15, 120, "东城区"),
                (cities[0], "南锣鼓巷", "胡同街巷、特色小店和老北京生活的城市切片。", ["文化", "美食", "购物"], "全天开放", 0, 120, "东城区"),
                (cities[1], "外滩", "沿黄浦江欣赏历史建筑群与陆家嘴天际线。", ["夜景", "文化", "休闲"], "全天开放", 0, 120, "黄浦区"),
                (cities[1], "上海博物馆", "从青铜器到书画，适合安排半天文化参观。", ["历史", "文化"], "09:00-17:00（周一闭馆）", 0, 180, "黄浦区"),
                (cities[1], "豫园", "江南园林、老城厢街巷与本帮美食集中地。", ["历史", "美食", "文化"], "09:00-16:30", 40, 120, "黄浦区"),
                (cities[1], "武康路", "梧桐树影和历史建筑，适合步行与街拍。", ["休闲", "文化", "美食"], "全天开放", 0, 150, "徐汇区"),
                (cities[2], "宽窄巷子", "老成都街巷、茶馆和地方小吃的集中体验区。", ["美食", "文化", "休闲"], "全天开放", 0, 120, "青羊区"),
                (cities[2], "大熊猫繁育研究基地", "近距离观察大熊猫，建议上午前往。", ["亲子", "自然"], "07:30-18:00", 55, 180, "成华区"),
                (cities[2], "武侯祠", "三国文化与红墙竹影相结合的历史景区。", ["历史", "文化"], "09:00-18:00", 50, 150, "武侯区"),
                (cities[2], "锦里古街", "夜间灯笼、地方小吃和传统市井氛围。", ["美食", "夜景", "文化"], "全天开放", 0, 120, "武侯区"),
            ]
            for city, name, description, tags, hours, price, duration, area in attractions:
                db.add(Attraction(city_id=city.id, name=name, description=description, tags=tags, opening_hours=hours, ticket_price=price, duration_minutes=duration, area=area, latitude=None, longitude=None, image_url=city.image_url))
        db.flush()
        sync_media_catalog(db)
        db.commit()
    finally:
        db.close()


def sync_media_catalog(db: Session) -> None:
    city_media = {
        "beijing": {
            "url": "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=1200&q=80",
            "alt_text": "北京故宫城市景观",
            "photo_id": "photo-1508804185872-d7badad00f7d",
            "status": "needs_review",
            "active": True,
        },
        "shanghai": {
            "url": "https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=1200&q=80",
            "alt_text": "上海城市天际线",
            "photo_id": "photo-1538428494232-9c0d8a3ab403",
            "status": "needs_review",
            "active": True,
        },
        "chengdu": {
            "url": "https://images.unsplash.com/photo-1548919973-5cef591cdbc9?auto=format&fit=crop&w=1200&q=80",
            "alt_text": "被误标为成都的上海城市图片",
            "photo_id": "photo-1548919973-5cef591cdbc9",
            "status": "rejected_wrong_city",
            "active": False,
        },
    }
    cities = list(db.scalars(select(City).order_by(City.id)))
    for city in cities:
        definition = city_media.get(city.slug)
        if not definition:
            continue
        asset = db.scalar(select(MediaAsset).where(
            MediaAsset.city_id == city.id,
            MediaAsset.attraction_id.is_(None),
            MediaAsset.purpose == "city_cover",
        ))
        values = {
            "content_key": f"{city.slug}:city:cover",
            "storage_type": "remote_url",
            "url": definition["url"],
            "storage_path": None,
            "mime_type": "image/jpeg",
            "alt_text": definition["alt_text"],
            "source_name": "Unsplash",
            "source_author": None,
            "license_name": "Unsplash License",
            "attribution_url": f"https://unsplash.com/photos/{definition['photo_id']}",
            "verification_status": definition["status"],
            "is_active": definition["active"],
        }
        if asset is None:
            asset = MediaAsset(city_id=city.id, attraction_id=None, purpose="city_cover", **values)
            db.add(asset)
        elif asset.verification_status == "approved" and not asset.source_author:
            asset.verification_status = "needs_review"
        city.image_url = asset.url if asset.is_active and asset.url else ""

        attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city.id).order_by(Attraction.id)))
        for attraction in attractions:
            asset = db.scalar(select(MediaAsset).where(
                MediaAsset.city_id == city.id,
                MediaAsset.attraction_id == attraction.id,
                MediaAsset.purpose == "attraction_cover",
            ))
            if asset is None:
                asset = MediaAsset(
                    city_id=city.id,
                    attraction_id=attraction.id,
                    purpose="attraction_cover",
                    content_key=f"{city.slug}:attraction:{attraction.id}:cover",
                    storage_type="remote_url",
                    url=None,
                    storage_path=None,
                    mime_type=None,
                    alt_text=f"{city.name}{attraction.name}景点图片",
                    source_name=None,
                    source_author=None,
                    license_name=None,
                    attribution_url=None,
                    verification_status="missing",
                    is_active=False,
                )
                db.add(asset)
            attraction.image_url = asset.url if asset.is_active and asset.url else ""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("__Host-access_token") or request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = decode_access_token(token)
        user = db.get(User, int(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录状态已失效") from exc
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


def owned_session(db: Session, user: User, session_id: int) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id or session.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    return session


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")


def ensure_csrf(request: Request) -> None:
    expected = request.cookies.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token")
    if expected and supplied and expected == supplied:
        return
    # Login and public read operations do not need CSRF. Mutating authenticated calls do.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (request.cookies.get("__Host-access_token") or request.cookies.get("access_token")):
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


def require_idempotency_key(value: str | None) -> str:
    if not value or len(value) > 120:
        raise HTTPException(status_code=400, detail="缺少或无效的 Idempotency-Key")
    return value


def idempotent_response(db: Session, user_id: int, session_id: int, action: str, key: str) -> dict | None:
    record = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.session_id == session_id,
        IdempotencyRecord.action == action,
        IdempotencyRecord.key == key,
    ))
    return record.response_data if record else None


def _cookie_names() -> tuple[str, str]:
    secure = settings.app_base_url.startswith("https://")
    return ("__Host-access_token", "__Host-refresh_token") if secure else ("access_token", "refresh_token")


def set_auth_cookies(response: Response, user: User, request: Request, db: Session, auth_session: AuthSession | None = None) -> None:
    secure = settings.app_base_url.startswith("https://")
    access_cookie, refresh_cookie = _cookie_names()
    refresh_token = new_refresh_token()
    csrf_token = new_csrf_token()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = now + timedelta(days=settings.refresh_token_days)
    if auth_session is None:
        auth_session = AuthSession(
            user_id=user.id,
            token_family_id=str(uuid.uuid4()),
            refresh_token_hash=token_hash(refresh_token),
            csrf_token_hash=token_hash(csrf_token),
            device_name=(request.headers.get("User-Agent") or "未知设备")[:200],
            last_used_at=now,
            expires_at=expires_at,
        )
        db.add(auth_session)
    else:
        auth_session.refresh_token_hash = token_hash(refresh_token)
        auth_session.csrf_token_hash = token_hash(csrf_token)
        auth_session.last_used_at = now
        auth_session.expires_at = expires_at
    db.commit()
    response.set_cookie(
        access_cookie,
        create_access_token(user.id, user.role),
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        refresh_cookie,
        refresh_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "csrf_token",
        csrf_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    for cookie_name in ["__Host-access_token", "access_token", "__Host-refresh_token", "refresh_token", "csrf_token"]:
        response.delete_cookie(cookie_name, path="/")


@app.get("/api/v1/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/api/v1/agent/status")
def agent_status():
    return get_llm_status()


@app.post("/api/v1/auth/login", response_model=UserOut)
def login(data: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    account = data.account.strip()
    user = db.scalar(select(User).where(
        User.is_active.is_(True),
        (func.lower(User.username) == account.lower()) | (func.lower(User.email) == account.lower()),
    ))
    if not user and re.fullmatch(r"\d{4}", account):
        user = db.scalar(select(User).where(User.public_id == account, User.is_active.is_(True)))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    set_auth_cookies(response, user, request, db)
    return user


@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201)
def register(data: RegisterIn, response: Response, request: Request, db: Session = Depends(get_db)):
    username = data.username.strip()
    email = str(data.email).strip().lower()
    if re.fullmatch(r"\d{4}", username):
        raise HTTPException(status_code=422, detail="用户名不能是 4 位纯数字，以免与用户 ID 混淆")
    if db.scalar(select(User).where((User.username == username) | (User.email == email))):
        raise HTTPException(status_code=409, detail="账号或邮箱已经注册")
    password_hash = hash_password(data.password)
    for _ in range(10):
        user = User(public_id=allocate_public_id(db), username=username, email=email, password_hash=password_hash, role="user")
        db.add(user)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if db.scalar(select(User).where((User.username == username) | (User.email == email))):
                raise HTTPException(status_code=409, detail="账号或邮箱已经注册")
    else:
        raise HTTPException(status_code=503, detail="用户 ID 分配冲突，请稍后重试")
    db.refresh(user)
    set_auth_cookies(response, user, request, db)
    return user


@app.post("/api/v1/auth/refresh", response_model=UserOut)
def refresh_auth(request: Request, response: Response, db: Session = Depends(get_db)):
    _, refresh_cookie = _cookie_names()
    refresh_token = request.cookies.get(refresh_cookie)
    csrf_cookie = request.cookies.get("csrf_token")
    csrf_header = request.headers.get("X-CSRF-Token")
    if not refresh_token or not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    auth_session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(refresh_token)))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if (
        not auth_session
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
        or not hmac.compare_digest(auth_session.csrf_token_hash, token_hash(csrf_cookie))
    ):
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    user = db.get(User, auth_session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    set_auth_cookies(response, user, request, db, auth_session)
    return user


@app.post("/api/v1/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    ensure_csrf(request)
    _, refresh_cookie = _cookie_names()
    refresh_token = request.cookies.get(refresh_cookie)
    if refresh_token:
        auth_session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(refresh_token)))
        if auth_session and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            auth_session.revoked_reason = "logout"
            db.commit()
    clear_auth_cookies(response)


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


def get_or_create_profile(db: Session, user_id: int) -> UserProfile:
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


@app.get("/api/v1/auth/profile", response_model=UserProfileOut)
def user_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = get_or_create_profile(db, user.id)
    db.commit()
    return profile


@app.patch("/api/v1/auth/profile", response_model=UserProfileOut)
def update_user_profile(data: UserProfileUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    profile = get_or_create_profile(db, user.id)
    profile.display_name = data.display_name.strip() if data.display_name else None
    profile.preferences = [item.strip() for item in data.preferences if item.strip()]
    profile.avoid_places = [item.strip() for item in data.avoid_places if item.strip()]
    db.commit()
    return profile


def current_auth_session(request: Request, db: Session, user_id: int) -> AuthSession | None:
    _, refresh_cookie = _cookie_names()
    refresh_token = request.cookies.get(refresh_cookie)
    if not refresh_token:
        return None
    return db.scalar(select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.refresh_token_hash == token_hash(refresh_token)))


@app.get("/api/v1/auth/sessions", response_model=list[AuthSessionOut])
def auth_sessions(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    current = current_auth_session(request, db, user.id)
    return [
        {
            "id": item.id,
            "device_name": item.device_name,
            "created_at": item.created_at,
            "last_used_at": item.last_used_at,
            "expires_at": item.expires_at,
            "current": bool(current and current.id == item.id),
        }
        for item in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).order_by(AuthSession.last_used_at.desc()))
    ]


@app.delete("/api/v1/auth/sessions/{auth_session_id}", status_code=204)
def revoke_auth_session(auth_session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    session = db.scalar(select(AuthSession).where(AuthSession.id == auth_session_id, AuthSession.user_id == user.id))
    if session and session.revoked_at is None:
        if current_auth_session(request, db, user.id) and current_auth_session(request, db, user.id).id == session.id:
            raise HTTPException(409, "当前设备请使用退出登录")
        session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.revoked_reason = "user"
        db.commit()


@app.post("/api/v1/auth/logout-all", status_code=204)
def logout_all(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now, revoked_reason="logout_all"))
    db.commit()
    clear_auth_cookies(response)


@app.post("/api/v1/auth/change-password", status_code=204)
def change_password(data: PasswordChangeIn, request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(401, "当前密码不正确")
    if data.current_password == data.new_password:
        raise HTTPException(422, "新密码不能与当前密码相同")
    user.password_hash = hash_password(data.new_password)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now, revoked_reason="password_changed"))
    db.commit()
    clear_auth_cookies(response)


@app.patch("/api/v1/auth/me/email", response_model=UserOut)
def change_email(data: EmailChangeIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "密码不正确")
    email = str(data.email).strip().lower()
    existing = db.scalar(select(User).where(User.email == email, User.id != user.id))
    if existing:
        raise HTTPException(409, "邮箱已经被使用")
    user.email = email
    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/v1/auth/me", status_code=204)
def delete_account(
    data: AccountDeleteIn,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ensure_csrf(request)
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="密码不正确，账号未注销")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(update(AuthSession).where(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).values(revoked_at=now, revoked_reason="account_deleted"))
    user.public_id = None
    user.is_active = False
    user.deleted_at = now
    db.commit()
    clear_auth_cookies(response)


@app.get("/api/v1/auth/csrf")
def csrf(response: Response):
    token = new_csrf_token()
    response.set_cookie("csrf_token", token, httponly=False, secure=settings.app_base_url.startswith("https://"), samesite="lax", path="/")
    return {"csrf_token": token}


@app.get("/api/v1/cities", response_model=list[CityOut])
def list_cities(db: Session = Depends(get_db)):
    return list(db.scalars(select(City).order_by(City.id)))


@app.get("/api/v1/cities/search", response_model=list[CityOut])
def search_cities(q: str = Query(default="", min_length=0, max_length=80), db: Session = Depends(get_db)):
    keyword = q.strip()
    if not keyword:
        return list(db.scalars(select(City).order_by(City.id)))
    return list(db.scalars(select(City).where(
        (City.name.contains(keyword)) | (City.slug.contains(keyword))
    ).order_by(City.id)))


@app.get("/api/v1/cities/{city_id}", response_model=CityOut)
def get_city(city_id: int, db: Session = Depends(get_db)):
    city = db.get(City, city_id)
    if not city:
        raise HTTPException(404, "城市不存在")
    return city


@app.get("/api/v1/cities/{city_id}/attractions", response_model=list[AttractionOut])
def city_attractions(city_id: int, db: Session = Depends(get_db)):
    if not db.get(City, city_id):
        raise HTTPException(404, "城市不存在")
    attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city_id)))
    return sorted(attractions, key=lambda item: (-attraction_hot_score(db, item), item.id))


@app.get("/api/v1/attractions/{attraction_id}", response_model=AttractionOut)
def get_attraction(attraction_id: int, db: Session = Depends(get_db)):
    attraction = db.get(Attraction, attraction_id)
    if not attraction:
        raise HTTPException(404, "景点不存在")
    return attraction


@app.get("/api/v1/media-assets", response_model=list[MediaAssetOut])
def list_media_assets(
    city_id: int | None = Query(default=None, ge=1),
    attraction_id: int | None = Query(default=None, ge=1),
    purpose: str | None = Query(default=None, max_length=40),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    query = select(MediaAsset)
    if city_id is not None:
        query = query.where(MediaAsset.city_id == city_id)
    if attraction_id is not None:
        query = query.where(MediaAsset.attraction_id == attraction_id)
    if purpose:
        query = query.where(MediaAsset.purpose == purpose)
    if not include_inactive:
        query = query.where(MediaAsset.is_active.is_(True))
    return list(db.scalars(query.order_by(MediaAsset.city_id, MediaAsset.attraction_id, MediaAsset.id)))


@app.get("/api/v1/rankings")
def rankings(type: str = "city", city_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db)):
    if type == "city":
        cities = list(db.scalars(select(City).order_by(City.id)))
        return [{"rank": index + 1, "name": city.name, "score": 96 - index * 4, "reason": city.season} for index, city in enumerate(cities)]
    if type != "attraction":
        raise HTTPException(status_code=400, detail="排行类型必须是 city 或 attraction")
    query = select(Attraction)
    if city_id is not None:
        if not db.get(City, city_id):
            raise HTTPException(status_code=404, detail="城市不存在")
        query = query.where(Attraction.city_id == city_id)
    attractions = list(db.scalars(query.order_by(Attraction.id)))
    scored = sorted(
        ((attraction, attraction_hot_score(db, attraction)) for attraction in attractions),
        key=lambda item: (-item[1], item[0].id),
    )[:10]
    return [
        {
            "rank": index + 1,
            "attraction_id": attraction.id,
            "city_id": attraction.city_id,
            "name": attraction.name,
            "score": score,
            "reason": "按资料权重计算，并叠加收藏、浏览和对话提及行为",
            "data_source": "weighted_behavior" if score > attraction_initial_hot_score(attraction) else "initialization_heuristic",
        }
        for index, (attraction, score) in enumerate(scored)
    ]


def attraction_initial_hot_score(attraction: Attraction) -> int:
    """Deterministic initial score until real search/click behavior is available."""
    tag_score = min(len(attraction.tags or []), 5) / 5 * 30
    accessibility_score = (10 if attraction.ticket_price == 0 else max(0, 10 - attraction.ticket_price // 10)) / 10 * 20
    duration_score = (10 if 90 <= attraction.duration_minutes <= 180 else 5) / 10 * 15
    completeness_score = sum(bool(value) for value in [attraction.description, attraction.opening_hours, attraction.area]) / 3 * 15
    diversity_score = min(len(set(attraction.tags or [])), 3) / 3 * 20
    return round(tag_score + accessibility_score + duration_score + completeness_score + diversity_score)


def attraction_hot_score(db: Session, attraction: Attraction) -> int:
    base_score = attraction_initial_hot_score(attraction)
    favorite_count = db.scalar(select(func.count(Favorite.id)).where(Favorite.target_type == "attraction", Favorite.target_id == attraction.id)) or 0
    view_count = db.scalar(select(func.count(RecentView.id)).where(RecentView.target_type == "attraction", RecentView.target_id == attraction.id)) or 0
    inquiry_count = db.scalar(select(func.count(ChatMessage.id)).join(ChatSession, ChatSession.id == ChatMessage.session_id).where(
        ChatMessage.role == "user",
        ChatMessage.content.contains(attraction.name),
    )) or 0
    behavior_score = min(25, favorite_count * 4 + view_count * 2 + inquiry_count * 2)
    return min(100, base_score + behavior_score)


DEFAULT_SESSION_TITLE = "新的旅行规划"


def session_title_from_message(content: str) -> str:
    title = re.sub(r"\s+", " ", content).strip(" ，。！？,.!?：:；;")
    if not title:
        return DEFAULT_SESSION_TITLE
    return f"{title[:22]}…" if len(title) > 22 else title


def backfill_session_titles() -> None:
    db = SessionLocal()
    try:
        unnamed_sessions = db.scalars(select(ChatSession).where(ChatSession.title == DEFAULT_SESSION_TITLE)).all()
        for session in unnamed_sessions:
            user_messages = db.scalars(select(ChatMessage.content).where(
                ChatMessage.session_id == session.id,
                ChatMessage.role == "user",
            ).order_by(ChatMessage.id)).all()
            generated_title = next(
                (session_title_from_message(message) for message in user_messages if session_title_from_message(message) != DEFAULT_SESSION_TITLE),
                None,
            )
            if generated_title:
                session.title = generated_title
            elif user_messages:
                session.title = f"旅行对话 {session.id}"
        db.commit()
    finally:
        db.close()


@app.get("/api/v1/sessions", response_model=list[SessionOut])
def sessions(archived: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    archive_filter = ChatSession.archived_at.is_not(None) if archived else ChatSession.archived_at.is_(None)
    return list(db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == user.id, ChatSession.deleted_at.is_(None), archive_filter)
        .order_by(ChatSession.is_pinned.desc(), func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc(), ChatSession.id.desc())
    ))


@app.post("/api/v1/sessions", response_model=SessionOut, status_code=201)
def create_session(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    session = ChatSession(user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.patch("/api/v1/sessions/{session_id}", response_model=SessionOut)
def update_session(
    session_id: int,
    data: SessionUpdateIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ensure_csrf(request)
    session = owned_session(db, user, session_id)
    if data.title is not None:
        title = data.title.strip()
        if not title:
            raise HTTPException(422, "会话名称不能为空")
        session.title = title
    if data.is_pinned is not None:
        session.is_pinned = data.is_pinned
    if data.archived is not None:
        session.archived_at = datetime.now(timezone.utc).replace(tzinfo=None) if data.archived else None
        if data.archived:
            session.is_pinned = False
    session.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(session)
    return session


@app.delete("/api/v1/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    session = owned_session(db, user, session_id)
    active_job = db.scalar(select(PlanningJob.id).where(
        PlanningJob.session_id == session_id,
        PlanningJob.status.in_(["queued", "running"]),
    ))
    if active_job:
        raise HTTPException(409, "当前会话仍有任务正在处理，请先停止任务")
    session.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.is_pinned = False
    session.updated_at = session.deleted_at
    db.commit()


@app.get("/api/v1/sessions/{session_id}/messages", response_model=list[MessageOut])
def session_messages(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_session(db, user, session_id)
    return list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)))


@app.post("/api/v1/sessions/{session_id}/messages", status_code=202)
async def send_message(
    session_id: int,
    data: MessageIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ensure_csrf(request)
    key = require_idempotency_key(idempotency_key)
    session = owned_session(db, user, session_id)
    existing = idempotent_response(db, user.id, session_id, "message", key)
    if existing:
        return existing
    active_job = db.scalar(select(PlanningJob).where(PlanningJob.session_id == session_id, PlanningJob.status.in_(["queued", "running"])))
    if active_job:
        raise HTTPException(status_code=409, detail="当前会话已有任务正在处理")
    if session.title == DEFAULT_SESSION_TITLE:
        session.title = session_title_from_message(data.content)
    session.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    message = ChatMessage(session_id=session_id, role="user", content=data.content)
    db.add(message)
    job = PlanningJob(session_id=session_id)
    db.add(job)
    db.flush()
    response_data = {"message_id": message.id, "turn_id": str(job.id), "job_id": job.id, "status": "queued", "session_title": session.title}
    db.add(IdempotencyRecord(user_id=user.id, session_id=session_id, action="message", key=key, response_data=response_data))
    db.commit()
    db.refresh(job)
    if settings.inline_worker:
        asyncio.create_task(process_job_async(job.id))
    return response_data


@app.post("/api/v1/sessions/{session_id}/plan-confirm", status_code=202)
async def plan_confirm(
    session_id: int,
    data: PlanConfirmIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ensure_csrf(request)
    key = require_idempotency_key(idempotency_key)
    session = owned_session(db, user, session_id)
    existing = idempotent_response(db, user.id, session_id, "plan_confirm", key)
    if existing:
        return existing
    confirmation = latest_confirmation(db, session_id)
    if not confirmation:
        raise HTTPException(status_code=409, detail="当前没有待确认的旅行需求")
    confirmed_job_id = (confirmation.payload or {}).get("confirmed_job_id")
    if confirmed_job_id:
        confirmed_job = db.get(PlanningJob, confirmed_job_id)
        response_data = {"job_id": confirmed_job_id, "status": confirmed_job.status if confirmed_job else "queued"}
        db.add(IdempotencyRecord(user_id=user.id, session_id=session_id, action="plan_confirm", key=key, response_data=response_data))
        db.commit()
        return response_data
    if not data.confirmed:
        response_data = {"job_id": None, "status": "declined"}
        db.add(IdempotencyRecord(user_id=user.id, session_id=session_id, action="plan_confirm", key=key, response_data=response_data))
        db.commit()
        return response_data
    active_job = db.scalar(select(PlanningJob).where(PlanningJob.session_id == session_id, PlanningJob.status.in_(["queued", "running"])))
    if active_job:
        raise HTTPException(status_code=409, detail="当前会话已有任务正在处理")
    allowed_patch = data.patch.model_dump(exclude_none=True)
    destination_city_id = allowed_patch.get("destination_city_id")
    if destination_city_id:
        city = db.get(City, destination_city_id)
        if not city or city.support_level != "full" or not city.planning_enabled:
            raise HTTPException(status_code=422, detail="所选城市暂不支持完整行程规划")
        allowed_patch["destination"] = city.name
    if "interests" in allowed_patch:
        allowed_patch["interests"] = list(dict.fromkeys(item.strip() for item in allowed_patch["interests"] if item.strip()))
    if "avoid_places" in allowed_patch:
        allowed_patch["avoid_places"] = list(dict.fromkeys(item.strip() for item in allowed_patch["avoid_places"] if item.strip()))
    confirmation.payload = {**(confirmation.payload or {}), **allowed_patch}
    confirmation.content = confirmation_message(confirmation.payload)
    job = PlanningJob(session_id=session_id, stage="plan_queued")
    db.add(job)
    db.flush()
    confirmation.payload = {**(confirmation.payload or {}), "confirmed_job_id": job.id}
    response_data = {"job_id": job.id, "status": "queued"}
    db.add(IdempotencyRecord(user_id=user.id, session_id=session_id, action="plan_confirm", key=key, response_data=response_data))
    db.commit()
    if settings.inline_worker:
        asyncio.create_task(process_job_async(job.id))
    return response_data


@app.post("/api/v1/sessions/{session_id}/stop")
def stop_session(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    owned_session(db, user, session_id)
    job = db.scalar(select(PlanningJob).where(PlanningJob.session_id == session_id, PlanningJob.status.in_(["queued", "running"])).order_by(PlanningJob.id.desc()))
    if not job:
        return {"status": "idle", "job_id": None}
    job.status, job.stage = "cancelled", "cancelled"
    db.commit()
    return {"status": "cancelled", "job_id": job.id}


@app.post("/api/v1/sessions/{session_id}/clear", status_code=204)
def clear_session(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    session = owned_session(db, user, session_id)
    db.execute(update(PlanningJob).where(PlanningJob.session_id == session_id, PlanningJob.status.in_(["queued", "running"])).values(status="cancelled", stage="cancelled"))
    session.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.is_pinned = False
    session.updated_at = session.deleted_at
    db.commit()


@app.get("/api/v1/sessions/{session_id}/events")
async def session_events(session_id: int, request: Request, after: int | None = Query(default=None, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_session(db, user, session_id)
    try:
        last_id = after if after is not None else int(request.headers.get("Last-Event-ID", "0"))
    except ValueError:
        last_id = 0
    earliest_id = db.scalar(select(func.min(AgentEvent.event_id)).where(AgentEvent.session_id == session_id))

    async def event_stream():
        cursor = last_id
        yield "retry: 3000\n\n"
        if cursor and earliest_id and cursor < earliest_id - 1:
            reset_data = {
                "event_id": None,
                "session_id": str(session_id),
                "turn_id": None,
                "type": "reset",
                "created_at": None,
                "payload": {"code": "EVENT_GONE", "message": "历史事件已过期，请重新同步"},
            }
            yield f"event: reset\ndata: {json.dumps(reset_data, ensure_ascii=False)}\n\n"
            return
        for tick in range(600):
            if await request.is_disconnected():
                return
            local_db = SessionLocal()
            try:
                events = list(local_db.scalars(select(AgentEvent).where(AgentEvent.session_id == session_id, AgentEvent.event_id > cursor).order_by(AgentEvent.event_id)))
                for event in events:
                    cursor = event.event_id
                    event_payload = dict(event.data or {})
                    turn_id = event_payload.pop("turn_id", None)
                    event_data = {
                        "event_id": event.event_id,
                        "session_id": str(session_id),
                        "turn_id": turn_id,
                        "type": event.event_type,
                        "created_at": event.created_at.isoformat(),
                        "payload": event_payload,
                    }
                    yield f"id: {event.event_id}\nevent: {event.event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                job = local_db.scalar(select(PlanningJob).where(PlanningJob.session_id == session_id).order_by(PlanningJob.id.desc()))
                if job and job.status in {"completed", "failed", "cancelled"} and not events:
                    return
            finally:
                local_db.close()
            if tick and tick % 30 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/v1/sessions/{session_id}/events/cursor")
def session_event_cursor(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_session(db, user, session_id)
    latest = db.scalar(select(func.max(AgentEvent.event_id)).where(AgentEvent.session_id == session_id)) or 0
    return {"last_event_id": latest}


@app.get("/api/v1/planning-jobs/{job_id}")
def planning_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(PlanningJob, job_id)
    session = db.get(ChatSession, job.session_id) if job else None
    if not job or not session or session.user_id != user.id or session.deleted_at is not None:
        raise HTTPException(404, "任务不存在")
    return {"id": job.id, "status": job.status, "stage": job.stage, "result_itinerary_id": job.result_itinerary_id, "error_message": job.error_message}


@app.get("/api/v1/itineraries")
def list_itineraries(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [itinerary_dict(db, itinerary.id) for itinerary in db.scalars(select(Itinerary).where(Itinerary.user_id == user.id).order_by(Itinerary.id.desc()))]


@app.get("/api/v1/itineraries/{itinerary_id}")
def get_itinerary(itinerary_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    itinerary = db.get(Itinerary, itinerary_id)
    if not itinerary or itinerary.user_id != user.id:
        raise HTTPException(404, "行程不存在")
    return itinerary_dict(db, itinerary_id)


@app.patch("/api/v1/itineraries/{itinerary_id}")
def save_itinerary(itinerary_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary = db.get(Itinerary, itinerary_id)
    if not itinerary or itinerary.user_id != user.id:
        raise HTTPException(404, "行程不存在")
    if itinerary.status != "saved":
        itinerary.status = "saved"
        itinerary.lock_version += 1
        db.commit()
    return itinerary_dict(db, itinerary_id)


@app.delete("/api/v1/itineraries/{itinerary_id}", status_code=204)
def delete_itinerary(itinerary_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary = db.get(Itinerary, itinerary_id)
    if not itinerary or itinerary.user_id != user.id:
        raise HTTPException(404, "行程不存在")
    validation = db.scalar(select(ItineraryValidation).where(ItineraryValidation.itinerary_id == itinerary_id))
    if validation:
        db.delete(validation)
    db.delete(itinerary)
    db.commit()


def itinerary_for_user(itinerary_id: int, user: User, db: Session) -> Itinerary:
    itinerary = db.get(Itinerary, itinerary_id)
    if not itinerary or itinerary.user_id != user.id:
        raise HTTPException(404, "行程不存在")
    return itinerary


def save_itinerary_revision(db: Session, itinerary_id: int, snapshot: dict, reason: str) -> None:
    latest = db.scalar(select(func.max(ItineraryRevision.version_no)).where(ItineraryRevision.itinerary_id == itinerary_id)) or 0
    db.add(ItineraryRevision(itinerary_id=itinerary_id, version_no=latest + 1, snapshot=snapshot, reason=reason))


def replace_itinerary_days(db: Session, itinerary: Itinerary, day_data: list[dict]) -> None:
    for day in list(itinerary.itinerary_days):
        for stop in list(day.stops):
            db.delete(stop)
        db.delete(day)
    db.flush()
    for item in day_data:
        day = ItineraryDay(itinerary_id=itinerary.id, day_number=item["day_number"], title=item["title"])
        db.add(day)
        db.flush()
        for stop in item.get("stops", []):
            stop_data = {key: value for key, value in stop.items() if key != "id"}
            db.add(ItineraryStop(day_id=day.id, **stop_data))


@app.put("/api/v1/itineraries/{itinerary_id}", response_model=dict)
def edit_itinerary(itinerary_id: int, data: ItineraryUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary = itinerary_for_user(itinerary_id, user, db)
    if data.expected_version is not None and data.expected_version != itinerary.lock_version:
        raise HTTPException(409, "行程已被其他页面更新，请刷新后再保存")
    snapshot = itinerary_dict(db, itinerary_id) or {}
    if data.title is not None:
        itinerary.title = data.title.strip()
    if data.days is not None:
        itinerary.days = data.days
    if data.budget_total is not None:
        itinerary.budget_total = data.budget_total
    if data.preferences is not None:
        itinerary.preferences = [item.strip() for item in data.preferences if item.strip()]
    if data.itinerary_days is not None:
        replace_itinerary_days(db, itinerary, [day.model_dump() for day in data.itinerary_days])
        itinerary.days = len(data.itinerary_days)
    itinerary.status = "saved"
    itinerary.lock_version += 1
    save_itinerary_revision(db, itinerary.id, snapshot, "用户编辑")
    db.commit()
    return itinerary_dict(db, itinerary_id)


@app.get("/api/v1/itineraries/{itinerary_id}/revisions", response_model=list[ItineraryRevisionOut])
def itinerary_revisions(itinerary_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    itinerary_for_user(itinerary_id, user, db)
    return list(db.scalars(select(ItineraryRevision).where(ItineraryRevision.itinerary_id == itinerary_id).order_by(ItineraryRevision.version_no.desc())))


@app.post("/api/v1/itineraries/{itinerary_id}/revisions/{version_no}/restore", response_model=dict)
def restore_itinerary_revision(itinerary_id: int, version_no: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary = itinerary_for_user(itinerary_id, user, db)
    revision = db.scalar(select(ItineraryRevision).where(ItineraryRevision.itinerary_id == itinerary_id, ItineraryRevision.version_no == version_no))
    if not revision:
        raise HTTPException(404, "历史版本不存在")
    current = itinerary_dict(db, itinerary_id) or {}
    save_itinerary_revision(db, itinerary.id, current, "恢复前自动保存")
    snapshot = revision.snapshot
    itinerary.title = snapshot.get("title", itinerary.title)
    itinerary.days = snapshot.get("days", itinerary.days)
    itinerary.budget_total = snapshot.get("budget_total", itinerary.budget_total)
    itinerary.preferences = snapshot.get("preferences", itinerary.preferences or [])
    replace_itinerary_days(db, itinerary, snapshot.get("itinerary_days", []))
    itinerary.lock_version += 1
    db.commit()
    return itinerary_dict(db, itinerary_id)


@app.post("/api/v1/itineraries/{itinerary_id}/replan", response_model=dict)
def replan_itinerary(itinerary_id: int, data: ReplanIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Apply safe, explicit natural-language edits locally; full LLM re-planning remains a later integration."""
    ensure_csrf(request)
    itinerary = itinerary_for_user(itinerary_id, user, db)
    instruction = data.instruction.strip()
    snapshot = itinerary_dict(db, itinerary_id) or {}
    day_match = re.search(r"(?:改成|调整为|安排为)\s*(\d+)\s*[天日]", instruction)
    budget_match = re.search(r"预算[^\d]{0,8}(\d{2,7})", instruction)
    delete_match = re.search(r"(?:删除|去掉|不要)[^，。；;]*?([\u4e00-\u9fff]{2,20})", instruction)
    replacement_match = re.search(r"(?:把|将)\s*([^，。；;]+?)\s*(?:替换成|换成)\s*([^，。；;]+)", instruction)
    if day_match:
        target_days = max(1, min(int(day_match.group(1)), 10))
        current_days = snapshot.get("itinerary_days", [])
        while len(current_days) < target_days:
            number = len(current_days) + 1
            current_days.append({"day_number": number, "title": f"第{number}天 · {itinerary.city_name}探索", "stops": []})
        snapshot["itinerary_days"] = current_days[:target_days]
    if budget_match:
        snapshot["budget_total"] = int(budget_match.group(1))
    if delete_match:
        keyword = delete_match.group(1).strip()
        for day in snapshot.get("itinerary_days", []):
            day["stops"] = [stop for stop in day.get("stops", []) if keyword not in stop.get("name", "")]
    if replacement_match:
        old_name, new_name = replacement_match.groups()
        replacement = db.scalar(select(Attraction).where(Attraction.city_id == db.scalar(select(City.id).where(City.name == itinerary.city_name)), Attraction.name.contains(new_name.strip())))
        for day in snapshot.get("itinerary_days", []):
            for stop in day.get("stops", []):
                if old_name.strip() in stop.get("name", "") and replacement:
                    stop["attraction_id"] = replacement.id
                    stop["name"] = replacement.name
                    stop["note"] = f"{replacement.area} · 建议游览{replacement.duration_minutes}分钟 · 开放时间{replacement.opening_hours}"
    if not any([day_match, budget_match, delete_match, replacement_match]):
        raise HTTPException(422, "请说明要调整的天数、预算、景点删除或替换内容")
    current = itinerary_dict(db, itinerary_id) or {}
    save_itinerary_revision(db, itinerary.id, current, "自然语言调整前自动保存")
    itinerary.budget_total = snapshot.get("budget_total", itinerary.budget_total)
    itinerary.days = len(snapshot.get("itinerary_days", []))
    replace_itinerary_days(db, itinerary, snapshot.get("itinerary_days", []))
    itinerary.lock_version += 1
    itinerary.status = "saved"
    db.commit()
    return itinerary_dict(db, itinerary_id)


@app.get("/api/v1/itineraries/{itinerary_id}/feedback")
def itinerary_feedback(itinerary_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    itinerary_for_user(itinerary_id, user, db)
    mine = db.scalar(select(ItineraryFeedback).where(ItineraryFeedback.itinerary_id == itinerary_id, ItineraryFeedback.user_id == user.id))
    values = list(db.scalars(select(ItineraryFeedback.rating).where(ItineraryFeedback.itinerary_id == itinerary_id)))
    return {"rating": mine.rating if mine else None, "comment": mine.comment if mine else "", "average": round(sum(values) / len(values), 1) if values else None, "count": len(values)}


@app.put("/api/v1/itineraries/{itinerary_id}/feedback", response_model=FeedbackOut)
def save_itinerary_feedback(itinerary_id: int, data: FeedbackIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary_for_user(itinerary_id, user, db)
    feedback = db.scalar(select(ItineraryFeedback).where(ItineraryFeedback.itinerary_id == itinerary_id, ItineraryFeedback.user_id == user.id))
    if not feedback:
        feedback = ItineraryFeedback(itinerary_id=itinerary_id, user_id=user.id, rating=data.rating, comment=data.comment.strip())
        db.add(feedback)
    else:
        feedback.rating = data.rating
        feedback.comment = data.comment.strip()
    db.commit()
    db.refresh(feedback)
    return feedback


@app.post("/api/v1/itineraries/{itinerary_id}/shares", response_model=ShareOut)
def create_share(itinerary_id: int, data: ShareCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary_for_user(itinerary_id, user, db)
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    share = ShareLink(itinerary_id=itinerary_id, token_hash=token_hash(raw_token), expires_at=now + timedelta(days=data.expires_days))
    db.add(share)
    db.commit()
    db.refresh(share)
    return {"id": share.id, "share_url": f"{settings.app_base_url.rstrip('/')}/share/itineraries/{raw_token}", "expires_at": share.expires_at, "created_at": share.created_at}


@app.get("/api/v1/shares/{token}")
def read_share(token: str, db: Session = Depends(get_db)):
    share = db.scalar(select(ShareLink).where(ShareLink.token_hash == token_hash(token), ShareLink.revoked_at.is_(None)))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not share or share.expires_at <= now:
        raise HTTPException(404, "分享链接不存在或已失效")
    return itinerary_dict(db, share.itinerary_id)


@app.delete("/api/v1/itineraries/{itinerary_id}/shares/{share_id}", status_code=204)
def revoke_share(itinerary_id: int, share_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary_for_user(itinerary_id, user, db)
    share = db.scalar(select(ShareLink).where(ShareLink.id == share_id, ShareLink.itinerary_id == itinerary_id))
    if share and share.revoked_at is None:
        share.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()


@app.get("/api/v1/favorites")
def list_favorites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    results = []
    for item in db.scalars(select(Favorite).where(Favorite.user_id == user.id).order_by(Favorite.id.desc())):
        target_model = City if item.target_type == "city" else Attraction if item.target_type == "attraction" else Itinerary
        target = db.get(target_model, item.target_id)
        if target:
            results.append({"target_type": item.target_type, "target_id": item.target_id, "name": getattr(target, "name", getattr(target, "title", "行程")), "description": getattr(target, "description", ""), "image_url": getattr(target, "image_url", ""), "city_id": getattr(target, "city_id", None)})
    return results


@app.put("/api/v1/favorites/{target_type}/{target_id}")
def add_favorite(target_type: str, target_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    target_model = City if target_type == "city" else Attraction if target_type == "attraction" else Itinerary if target_type == "itinerary" else None
    if not target_model or not db.get(target_model, target_id):
        raise HTTPException(404, "收藏对象不存在")
    existing = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.target_type == target_type, Favorite.target_id == target_id))
    if not existing:
        db.add(Favorite(user_id=user.id, target_type=target_type, target_id=target_id))
        db.commit()
    return {"ok": True}


@app.delete("/api/v1/favorites/{target_type}/{target_id}", status_code=204)
def remove_favorite(target_type: str, target_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    item = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.target_type == target_type, Favorite.target_id == target_id))
    if item:
        db.delete(item)
        db.commit()


@app.get("/api/v1/recent-views")
def list_recent_views(user: User = Depends(current_user), db: Session = Depends(get_db)):
    results = []
    for item in db.scalars(select(RecentView).where(RecentView.user_id == user.id).order_by(RecentView.viewed_at.desc()).limit(50)):
        target = db.get(City if item.target_type == "city" else Attraction, item.target_id)
        if target:
            results.append({"target_type": item.target_type, "target_id": item.target_id, "name": target.name, "description": target.description, "image_url": target.image_url, "viewed_at": item.viewed_at})
    return results


@app.post("/api/v1/recent-views", status_code=204)
def add_recent_view(target_type: str, target_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    target_model = City if target_type == "city" else Attraction if target_type == "attraction" else None
    if not target_model or not db.get(target_model, target_id):
        raise HTTPException(404, "浏览对象不存在")
    item = db.scalar(select(RecentView).where(RecentView.user_id == user.id, RecentView.target_type == target_type, RecentView.target_id == target_id))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if item:
        item.viewed_at = now
    else:
        db.add(RecentView(user_id=user.id, target_type=target_type, target_id=target_id, viewed_at=now))
    db.commit()


@app.delete("/api/v1/recent-views", status_code=204)
def clear_recent_views(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    db.execute(delete(RecentView).where(RecentView.user_id == user.id))
    db.commit()


@app.get("/api/v1/admin/overview")
def admin_overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    return {
        "cities": db.scalar(select(func.count(City.id))),
        "attractions": db.scalar(select(func.count(Attraction.id))),
        "users": db.scalar(select(func.count(User.id))),
        "jobs": db.scalar(select(func.count(PlanningJob.id))),
        "sessions": db.scalar(select(func.count(ChatSession.id))),
        "deleted_sessions": db.scalar(select(func.count(ChatSession.id)).where(ChatSession.deleted_at.is_not(None))),
        "feedback": db.scalar(select(func.count(ItineraryFeedback.id))),
    }


@app.get("/api/v1/admin/users", response_model=list[AdminUserOut])
def admin_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    results = []
    for account in db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())):
        results.append({
            "id": account.id,
            "public_id": account.public_id,
            "username": account.username,
            "email": account.email,
            "role": account.role,
            "is_active": account.is_active,
            "created_at": account.created_at,
            "session_count": db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == account.id)) or 0,
            "deleted_session_count": db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == account.id, ChatSession.deleted_at.is_not(None))) or 0,
        })
    return results


@app.get("/api/v1/admin/feedback", response_model=list[AdminFeedbackOut])
def admin_feedback(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    results = []
    for feedback in db.scalars(select(ItineraryFeedback).order_by(ItineraryFeedback.created_at.desc()).limit(200)):
        itinerary = db.get(Itinerary, feedback.itinerary_id)
        owner = db.get(User, feedback.user_id)
        if itinerary and owner:
            results.append({
                "id": feedback.id,
                "itinerary_id": itinerary.id,
                "username": owner.username,
                "email": owner.email,
                "city_name": itinerary.city_name,
                "itinerary_title": itinerary.title,
                "rating": feedback.rating,
                "comment": feedback.comment or "",
                "created_at": feedback.created_at,
                "updated_at": feedback.updated_at,
            })
    return results


@app.patch("/api/v1/admin/users/{user_id}", response_model=AdminUserOut)
def admin_update_user(user_id: int, data: AdminUserUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    account = db.get(User, user_id)
    if not account:
        raise HTTPException(404, "用户不存在")
    if account.deleted_at is not None:
        raise HTTPException(409, "已注销账号不能重新启用")
    if account.id == user.id and not data.is_active:
        raise HTTPException(409, "不能停用当前登录的管理员账号")
    account.is_active = data.is_active
    if not data.is_active:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.execute(update(AuthSession).where(AuthSession.user_id == account.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now, revoked_reason="admin_disabled"))
    db.commit()
    session_count = db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == account.id)) or 0
    deleted_count = db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == account.id, ChatSession.deleted_at.is_not(None))) or 0
    return {
        "id": account.id, "public_id": account.public_id, "username": account.username, "email": account.email, "role": account.role,
        "is_active": account.is_active, "created_at": account.created_at,
        "session_count": session_count, "deleted_session_count": deleted_count,
    }


@app.get("/api/v1/admin/sessions", response_model=list[AdminSessionOut])
def admin_sessions(state: str = "all", limit: int = Query(default=100, ge=1, le=200), user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    if state not in {"all", "active", "archived", "deleted"}:
        raise HTTPException(422, "无效的会话状态")
    statement = select(ChatSession).order_by(func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc(), ChatSession.id.desc()).limit(limit)
    if state == "active":
        statement = statement.where(ChatSession.deleted_at.is_(None), ChatSession.archived_at.is_(None))
    elif state == "archived":
        statement = statement.where(ChatSession.deleted_at.is_(None), ChatSession.archived_at.is_not(None))
    elif state == "deleted":
        statement = statement.where(ChatSession.deleted_at.is_not(None))
    results = []
    for chat in db.scalars(statement):
        owner = db.get(User, chat.user_id) if chat.user_id else None
        chat_state = "deleted" if chat.deleted_at else "archived" if chat.archived_at else "active"
        results.append({
            "id": chat.id,
            "user_id": chat.user_id,
            "username": owner.username if owner else "已注销用户",
            "email": owner.email if owner else "-",
            "title": chat.title,
            "state": chat_state,
            "message_count": db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.session_id == chat.id)) or 0,
            "job_count": db.scalar(select(func.count(PlanningJob.id)).where(PlanningJob.session_id == chat.id)) or 0,
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
            "deleted_at": chat.deleted_at,
        })
    return results


@app.post("/api/v1/admin/sessions/{session_id}/restore", response_model=AdminSessionOut)
def admin_restore_session(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    chat = db.get(ChatSession, session_id)
    if not chat:
        raise HTTPException(404, "会话不存在")
    chat.deleted_at = None
    chat.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    owner = db.get(User, chat.user_id) if chat.user_id else None
    return {
        "id": chat.id, "user_id": chat.user_id, "username": owner.username if owner else "已注销用户",
        "email": owner.email if owner else "-", "title": chat.title,
        "state": "archived" if chat.archived_at else "active",
        "message_count": db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.session_id == chat.id)) or 0,
        "job_count": db.scalar(select(func.count(PlanningJob.id)).where(PlanningJob.session_id == chat.id)) or 0,
        "created_at": chat.created_at, "updated_at": chat.updated_at, "deleted_at": None,
    }
