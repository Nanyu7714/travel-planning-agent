import asyncio
import copy
import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token, hash_password, new_csrf_token, new_refresh_token, password_needs_rehash, token_hash, verify_password
from app.db import SessionLocal, engine, get_db
from app.llm import generate_replan_interpretation, get_llm_status
from app.mail import AuthMail, MailDeliveryError, action_email_html, send_auth_mail, verification_email_html
from app.media import collect_photo_candidates, download_image, sanitize_image_bytes, search_amap_place, search_commons_image
from app.modules.system.router import router as system_router
from app.models import AdminAuditLog, AgentEvent, AgentRun, AgentToolCall, Attraction, AuthActionToken, AuthRateLimitBucket, AuthSession, ChatMessage, ChatSession, City, CommunityComment, CommunityPost, CommunityPostFavorite, CommunityPostImage, CommunityPostLike, ContentReport, EmailOutbox, Favorite, IdempotencyRecord, Itinerary, ItineraryDay, ItineraryFeedback, ItineraryRevision, ItineraryStop, ItineraryValidation, KnowledgeChunk, KnowledgeDocument, MediaAsset, PlanningJob, RankingEntry, RecentView, ShareLink, User, UserProfile
from app.schemas import AccountDeleteIn, AdminAttractionCreateIn, AdminAttractionImportIn, AdminAttractionOut, AdminAttractionUpdateIn, AdminAuditLogOut, AdminAuditLogPageOut, AdminCityCreateIn, AdminCityImportIn, AdminCityOut, AdminCityUpdateIn, AdminEmailOutboxOut, AdminEmailOutboxPageOut, AdminFeedbackOut, AdminFeedbackPageOut, AdminFeedbackUpdateIn, AdminItineraryOut, AdminItineraryPageOut, AdminKnowledgeDocumentOut, AdminPhotoFetchIn, AdminPhotoFetchOut, AdminRankingCreateIn, AdminRankingImportIn, AdminRankingOut, AdminRankingUpdateIn, AdminSessionOut, AdminSessionPageOut, AdminUserOut, AdminUserPageOut, AdminUserUpdateIn, AttractionOut, AuthActionOut, AuthSessionOut, AuthTokenIn, CityOut, CommunityCommentCreateIn, CommunityPostCreateIn, CommunityPostUpdateIn, CommunityStatusUpdateIn, ContentReportCreateIn, ContentReportStatusUpdateIn, EmailChangeIn, EmailRequestIn, EmailVerificationIn, FeedbackIn, FeedbackOut, ItineraryRevisionOut, ItineraryUpdateIn, KnowledgeDocumentIn, KnowledgeDocumentUpdateIn, LoginIn, MediaAssetBulkUpdateIn, MediaAssetOut, MediaAssetUpdateIn, MessageIn, MessageOut, PasswordChangeIn, PasswordResetIn, PlanConfirmIn, RegisterIn, ReplanActionIn, ReplanIn, ReplanPreviewOut, SessionBulkUpdateIn, SessionOut, SessionUpdateIn, ShareCreateIn, ShareHistoryOut, ShareOut, UserOut, UserProfileOut, UserProfileUpdateIn
from app.services import CITY_NAMES, confirmation_message, itinerary_dict, latest_confirmation, process_job_async, rebuild_knowledge_chunks, search_guide_knowledge


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_database_migrated()
    seed_database()
    backfill_user_public_ids()
    backfill_session_titles()
    yield


app = FastAPI(title="行旅旅游规划 Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.app_base_url], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(system_router, prefix="/api/v1")
MEDIA_ROOT = Path(__file__).resolve().parent.parent / "media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")
logger = logging.getLogger(__name__)


def alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parent.parent
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


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


def ensure_database_migrated() -> None:
    config = alembic_config()
    expected_revision = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    if current_revision != expected_revision:
        raise RuntimeError(
            "Database schema is not at the required Alembic revision. "
            "Run `alembic upgrade head` before starting the application. "
            "For an existing pre-Alembic database, back it up and run `alembic stamp head` followed by `alembic check`."
        )


def seed_database() -> None:
    db = SessionLocal()
    try:
        if not db.scalar(select(User).where(User.username == "admin")):
            if not settings.admin_initial_password:
                raise RuntimeError("ADMIN_INITIAL_PASSWORD must be configured before creating the initial administrator")
            db.add(User(username="admin", email="admin@travel.local", password_hash=hash_password(settings.admin_initial_password), role="admin", email_verified_at=datetime.now(timezone.utc).replace(tzinfo=None)))
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
        asset = db.scalar(select(MediaAsset).where(
            MediaAsset.city_id == city.id,
            MediaAsset.attraction_id.is_(None),
            MediaAsset.purpose == "city_cover",
        ))
        if asset is None:
            if definition:
                asset = MediaAsset(
                    city_id=city.id, attraction_id=None, purpose="city_cover",
                    content_key=f"{city.slug}:city:cover",
                    storage_type="remote_url",
                    url=definition["url"],
                    storage_path=None,
                    mime_type="image/jpeg",
                    alt_text=definition["alt_text"],
                    source_name="Unsplash",
                    source_author=None,
                    license_name="Unsplash License",
                    attribution_url=f"https://unsplash.com/photos/{definition['photo_id']}",
                    verification_status=definition["status"],
                    is_active=definition["active"],
                )
                db.add(asset)
            else:
                # City without a curated source: create an empty cover slot so
                # admins can autofill or upload an image from the media page.
                asset = MediaAsset(
                    city_id=city.id, attraction_id=None, purpose="city_cover",
                    content_key=f"{city.slug}:city:cover",
                    storage_type="remote_url",
                    url=None,
                    storage_path=None,
                    mime_type=None,
                    alt_text=f"{city.name}城市封面",
                    source_name=None,
                    source_author=None,
                    license_name=None,
                    attribution_url=None,
                    verification_status="missing",
                    is_active=False,
                )
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


def media_display_url(asset: MediaAsset) -> str | None:
    if asset.storage_type == "local_file" and asset.storage_path:
        return f"/media/{asset.storage_path.lstrip('/')}"
    return asset.url


def sync_media_display_target(db: Session, asset: MediaAsset) -> None:
    display_url = media_display_url(asset) if asset.is_active and asset.verification_status == "approved" else ""
    if asset.attraction_id is not None:
        attraction = db.get(Attraction, asset.attraction_id)
        if attraction:
            attraction.image_url = display_url or ""
    elif asset.purpose == "city_cover":
        city = db.get(City, asset.city_id)
        if city:
            city.image_url = display_url or ""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("__Host-access_token") or request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        session_id = int(payload["sid"])
        user = db.get(User, user_id)
        auth_session = db.scalar(select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        ))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录状态已失效") from exc
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    if not auth_session or auth_session.expires_at <= now:
        raise HTTPException(status_code=401, detail="登录状态已失效")
    request.state.auth_session = auth_session
    return user


def owned_session(db: Session, user: User, session_id: int) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id or session.deleted_at is not None:
        raise HTTPException(404, "会话不存在")
    return session


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")


def record_admin_audit(db: Session, user: User, action: str, target_type: str, target_id: int | None, summary: str, payload: dict | None = None) -> None:
    db.add(AdminAuditLog(
        actor_user_id=user.id,
        actor_username=user.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        payload=payload,
    ))


def ensure_csrf(request: Request) -> None:
    expected = request.cookies.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token")
    auth_session = getattr(request.state, "auth_session", None)
    valid = bool(
        expected
        and supplied
        and auth_session
        and hmac.compare_digest(expected, supplied)
        and hmac.compare_digest(auth_session.csrf_token_hash, token_hash(expected))
    )
    if not valid:
        raise HTTPException(status_code=403, detail="CSRF 校验失败")


AUTH_RATE_RULES = {
    "login": (900, 5, 60),
    "register": (3600, 5, 30),
    "resend_verification": (3600, 3, 30),
    "verify_email": (900, 10, 40),
    "forgot_password": (3600, 3, 30),
    "reset_password": (900, 10, 40),
    "change_email": (3600, 5, 30),
    "confirm_email_change": (900, 10, 40),
}
VERIFICATION_RESEND_COOLDOWN_SECONDS = 60


def ensure_public_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    if not origin or hmac.compare_digest(origin.rstrip("/"), settings.app_base_url.rstrip("/")):
        return
    origin_host = urlsplit(origin).hostname
    expected_host = urlsplit(settings.app_base_url).hostname
    if settings.environment == "development" and origin_host in {"localhost", "127.0.0.1"} and expected_host in {"localhost", "127.0.0.1"}:
        return
    raise HTTPException(status_code=403, detail="请求来源不受信任")


def _rate_scope_hash(scope_type: str, value: str) -> str:
    normalized = value.strip().lower()
    return hmac.new(settings.csrf_secret.encode(), f"{scope_type}:{normalized}".encode(), hashlib.sha256).hexdigest()


def enforce_auth_rate_limit(db: Session, request: Request, action: str, account_key: str) -> None:
    window_seconds, account_limit, ip_limit = AUTH_RATE_RULES[action]
    client_ip = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for scope_type, value, limit in (("account", account_key, account_limit), ("ip", client_ip, ip_limit)):
        scope_hash = _rate_scope_hash(scope_type, value)
        bucket = db.scalar(select(AuthRateLimitBucket).where(
            AuthRateLimitBucket.action == action,
            AuthRateLimitBucket.scope_type == scope_type,
            AuthRateLimitBucket.scope_hash == scope_hash,
        ))
        if bucket is None:
            bucket = AuthRateLimitBucket(
                action=action,
                scope_type=scope_type,
                scope_hash=scope_hash,
                window_started_at=now,
                attempt_count=0,
            )
            db.add(bucket)
            db.flush()
        window_ends_at = bucket.window_started_at + timedelta(seconds=window_seconds)
        if now >= window_ends_at:
            bucket.window_started_at = now
            bucket.attempt_count = 0
            bucket.blocked_until = None
            window_ends_at = now + timedelta(seconds=window_seconds)
        if bucket.blocked_until and bucket.blocked_until > now:
            retry_after = max(1, int((bucket.blocked_until - now).total_seconds()))
            raise HTTPException(429, "请求过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
        if bucket.attempt_count >= limit:
            bucket.blocked_until = window_ends_at
            db.commit()
            retry_after = max(1, int((window_ends_at - now).total_seconds()))
            raise HTTPException(429, "请求过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
        bucket.attempt_count += 1
    db.commit()


def clear_auth_account_rate_limit(db: Session, action: str, account_key: str) -> None:
    db.execute(delete(AuthRateLimitBucket).where(
        AuthRateLimitBucket.action == action,
        AuthRateLimitBucket.scope_type == "account",
        AuthRateLimitBucket.scope_hash == _rate_scope_hash("account", account_key),
    ))
    db.commit()


def mask_email(email: str) -> str:
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = f"{local[:1]}*"
    elif len(local) <= 4:
        masked_local = f"{local[:1]}{'*' * (len(local) - 2)}{local[-1:]}"
    else:
        masked_local = f"{local[:2]}{'*' * (len(local) - 4)}{local[-2:]}"
    return f"{masked_local}@{domain}"


def email_recipient_fingerprint(email: str) -> str:
    return hmac.new(
        settings.csrf_secret.encode("utf-8"),
        email.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def send_tracked_auth_mail(db: Session, user: User, purpose: str, message: AuthMail) -> None:
    """Persist only delivery metadata; mail content and one-time credentials stay out of the outbox."""
    delivery = EmailOutbox(
        user_id=user.id,
        purpose=purpose,
        recipient_fingerprint=email_recipient_fingerprint(message.recipient),
        recipient_masked=mask_email(message.recipient),
        subject=message.subject,
        status="pending",
    )
    db.add(delivery)
    db.commit()
    try:
        result = send_auth_mail(message)
    except MailDeliveryError as exc:
        delivery.status = "failed"
        delivery.attempt_count = exc.attempt_count
        delivery.retry_count = max(0, exc.attempt_count - 1)
        delivery.last_error_code = exc.code[:80]
        db.commit()
        raise

    delivery.status = result.status
    delivery.attempt_count = result.attempt_count
    delivery.retry_count = max(0, result.attempt_count - 1)
    delivery.last_error_code = None
    delivery.sent_at = datetime.now(timezone.utc).replace(tzinfo=None) if result.status == "sent" else None
    db.commit()


def verification_retry_after(db: Session, user_id: int) -> int:
    latest = db.scalar(select(AuthActionToken).where(
        AuthActionToken.user_id == user_id,
        AuthActionToken.purpose == "verify_email",
        AuthActionToken.used_at.is_(None),
    ).order_by(AuthActionToken.created_at.desc()))
    if latest is None:
        return 0
    elapsed = (datetime.now(timezone.utc).replace(tzinfo=None) - latest.created_at).total_seconds()
    return min(
        VERIFICATION_RESEND_COOLDOWN_SECONDS,
        max(0, int(VERIFICATION_RESEND_COOLDOWN_SECONDS - elapsed + 0.999)),
    )


def verification_response(email: str) -> dict:
    masked = mask_email(email)
    return {
        "message": f"如果该邮箱需要验证，验证码已发送至 {masked}，验证码 {settings.email_verification_code_minutes} 分钟内有效；60 秒后可以重新发送。",
        "masked_email": masked,
        "expires_in_seconds": settings.email_verification_code_minutes * 60,
        "retry_after_seconds": VERIFICATION_RESEND_COOLDOWN_SECONDS,
    }


def issue_email_verification_code(db: Session, user: User, target_email: str) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(update(AuthActionToken).where(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == "verify_email",
        AuthActionToken.used_at.is_(None),
    ).values(used_at=now))
    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    action_token = AuthActionToken(
        user_id=user.id,
        purpose="verify_email",
        token_hash=token_hash(f"verify_email:{target_email.lower()}:{raw_code}"),
        target_email=target_email,
        expires_at=now + timedelta(minutes=settings.email_verification_code_minutes),
        created_at=now,
    )
    db.add(action_token)
    db.commit()
    try:
        send_tracked_auth_mail(db, user, "verify_email", AuthMail(
            recipient=target_email,
            subject="你的行旅邮箱验证码",
            body=f"你的邮箱验证码是：{raw_code}\n\n验证码将在 {settings.email_verification_code_minutes} 分钟后失效，请勿告诉他人。",
            html_body=verification_email_html(raw_code, settings.email_verification_code_minutes),
        ))
    except MailDeliveryError as exc:
        logger.warning("Auth email delivery failed: %s", type(exc).__name__)
        action_token.used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        raise HTTPException(status_code=503, detail="验证码暂时发送失败，请稍后重试") from exc


def issue_auth_action(db: Session, user: User, purpose: str, target_email: str, path: str, expires_minutes: int) -> str | None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(update(AuthActionToken).where(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == purpose,
        AuthActionToken.used_at.is_(None),
    ).values(used_at=now))
    raw_token = secrets.token_urlsafe(48)
    action_token = AuthActionToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=token_hash(raw_token),
        target_email=target_email,
        expires_at=now + timedelta(minutes=expires_minutes),
    )
    db.add(action_token)
    db.commit()
    action_url = f"{settings.app_base_url.rstrip('/')}{path}?{urlencode({'token': raw_token})}"
    subject_map = {
        "reset_password": "重置你的行旅密码",
        "change_email": "确认新的行旅邮箱",
    }
    body_map = {
        "reset_password": f"请打开下面的链接重置密码。链接将在 {expires_minutes} 分钟后失效。\n\n{action_url}",
        "change_email": f"请打开下面的链接确认新邮箱。链接将在 {expires_minutes} 分钟后失效。\n\n{action_url}",
    }
    action_label_map = {
        "reset_password": "重设密码",
        "change_email": "确认新邮箱",
    }
    try:
        send_tracked_auth_mail(db, user, purpose, AuthMail(
            recipient=target_email,
            subject=subject_map[purpose],
            body=body_map[purpose],
            html_body=action_email_html(subject_map[purpose], action_label_map[purpose], action_url, expires_minutes),
        ))
    except MailDeliveryError as exc:
        logger.warning("Auth email delivery failed: %s", type(exc).__name__)
        action_token.used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        raise HTTPException(status_code=503, detail="邮件暂时发送失败，请稍后重试") from exc
    if settings.environment == "development" and settings.mail_delivery_mode == "console":
        return action_url
    return None


def valid_auth_action(db: Session, raw_token: str, purpose: str) -> AuthActionToken:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    action_token = db.scalar(select(AuthActionToken).where(
        AuthActionToken.token_hash == token_hash(raw_token),
        AuthActionToken.purpose == purpose,
        AuthActionToken.used_at.is_(None),
        AuthActionToken.expires_at > now,
    ))
    if action_token is None:
        raise HTTPException(400, "链接无效、已过期或已经使用")
    return action_token


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
    db.flush()
    db.commit()
    response.set_cookie(
        access_cookie,
        create_access_token(user.id, user.role, auth_session.id),
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


@app.get("/api/v1/admin/agent-status")
def admin_agent_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Diagnostics are restricted to administrators so model failure details stay out of the public UI."""
    require_admin(user)
    status_payload = get_llm_status(include_diagnostics=True)
    status_payload["runs"] = {
        "completed": db.scalar(select(func.count(AgentRun.id)).where(AgentRun.status == "completed")) or 0,
        "failed": db.scalar(select(func.count(AgentRun.id)).where(AgentRun.status == "failed")) or 0,
        "running": db.scalar(select(func.count(AgentRun.id)).where(AgentRun.status == "running")) or 0,
    }
    return status_payload


@app.post("/api/v1/auth/login", response_model=UserOut)
def login(data: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    ensure_public_origin(request)
    account = data.account.strip()
    enforce_auth_rate_limit(db, request, "login", account)
    user = db.scalar(select(User).where(
        User.is_active.is_(True),
        (func.lower(User.username) == account.lower()) | (func.lower(User.email) == account.lower()),
    ))
    if not user and re.fullmatch(r"\d{4}", account):
        user = db.scalar(select(User).where(User.public_id == account, User.is_active.is_(True)))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="邮箱尚未验证，请先完成邮箱验证")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
        db.commit()
    clear_auth_account_rate_limit(db, "login", account)
    set_auth_cookies(response, user, request, db)
    return user


@app.post("/api/v1/auth/register", response_model=AuthActionOut, status_code=202)
def register(data: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ensure_public_origin(request)
    username = data.username.strip()
    email = str(data.email).strip().lower()
    enforce_auth_rate_limit(db, request, "register", email)
    if re.fullmatch(r"\d{4}", username):
        raise HTTPException(status_code=422, detail="用户名不能是 4 位纯数字，以免与用户 ID 混淆")
    existing_username = db.scalar(select(User).where(User.username == username))
    existing_email = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing_username:
        if existing_username.email.lower() != email:
            can_correct = (
                existing_username.is_active
                and existing_username.email_verified_at is None
                and existing_email is None
                and verify_password(data.password, existing_username.password_hash)
            )
            if not can_correct:
                raise HTTPException(status_code=409, detail="用户名已被使用，请更换用户名")
            existing_username.email = email
            db.execute(update(AuthActionToken).where(
                AuthActionToken.user_id == existing_username.id,
                AuthActionToken.purpose == "verify_email",
                AuthActionToken.used_at.is_(None),
            ).values(used_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail="邮箱已被使用，请更换邮箱") from exc
            return {
                "message": f"邮箱已更正为 {mask_email(email)}，请点击“发送验证码”。",
                "masked_email": mask_email(email),
                "retry_after_seconds": 0,
            }
        if existing_username.is_active and existing_username.email_verified_at is None:
            return {
                "message": "账号已创建但邮箱尚未验证，请点击“发送验证码”。",
                "masked_email": mask_email(email),
                "retry_after_seconds": 0,
            }
        raise HTTPException(status_code=409, detail="用户名已被使用，请更换用户名")
    if existing_email:
        return {"message": "如果资料可以注册，账号已创建，请继续邮箱验证。"}
    password_hash = hash_password(data.password)
    for _ in range(10):
        user = User(public_id=allocate_public_id(db), username=username, email=email, password_hash=password_hash, role="user", email_verified_at=None)
        db.add(user)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if db.scalar(select(User).where(User.username == username)):
                raise HTTPException(status_code=409, detail="用户名已被使用，请更换用户名")
            if db.scalar(select(User).where(func.lower(User.email) == email)):
                return {"message": "如果资料可以注册，账号已创建，请继续邮箱验证。"}
    else:
        raise HTTPException(status_code=503, detail="用户 ID 分配冲突，请稍后重试")
    return {
        "message": "账号已创建，请发送验证码完成邮箱验证。",
        "masked_email": mask_email(email),
        "retry_after_seconds": 0,
    }


@app.post("/api/v1/auth/verify-email", response_model=AuthActionOut)
def verify_email(data: EmailVerificationIn, request: Request, db: Session = Depends(get_db)):
    ensure_public_origin(request)
    email = str(data.email).strip().lower()
    enforce_auth_rate_limit(db, request, "verify_email", email)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    action_token = db.scalar(select(AuthActionToken).where(
        AuthActionToken.token_hash == token_hash(f"verify_email:{email}:{data.code}"),
        AuthActionToken.purpose == "verify_email",
        AuthActionToken.target_email == email,
        AuthActionToken.used_at.is_(None),
        AuthActionToken.expires_at > now,
    ))
    if action_token is None:
        raise HTTPException(400, "验证码错误或已过期")
    user = db.get(User, action_token.user_id)
    if not user or not user.is_active or user.email.lower() != email:
        raise HTTPException(400, "验证码错误或已过期")
    user.email_verified_at = now
    db.execute(update(AuthActionToken).where(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == "verify_email",
        AuthActionToken.used_at.is_(None),
    ).values(used_at=now))
    db.commit()
    return {"message": "邮箱验证成功，现在可以登录。"}


@app.post("/api/v1/auth/send-verification-code", response_model=AuthActionOut, status_code=202)
@app.post("/api/v1/auth/resend-verification", response_model=AuthActionOut, status_code=202)
def resend_verification(data: EmailRequestIn, request: Request, db: Session = Depends(get_db)):
    ensure_public_origin(request)
    email = str(data.email).strip().lower()
    enforce_auth_rate_limit(db, request, "resend_verification", email)
    user = db.scalar(select(User).where(func.lower(User.email) == email, User.is_active.is_(True)))
    if user and user.email_verified_at is None:
        retry_after = verification_retry_after(db, user.id)
        if retry_after:
            return {
                "message": f"如果该邮箱需要验证，验证码已发送至 {mask_email(email)}，请检查收件箱；{retry_after} 秒后可以重新发送。",
                "masked_email": mask_email(email),
                "expires_in_seconds": settings.email_verification_code_minutes * 60,
                "retry_after_seconds": retry_after,
            }
        issue_email_verification_code(db, user, email)
        return verification_response(email)
    return {
        "message": f"如果该邮箱需要验证，验证码已发送至 {mask_email(email)}，请检查收件箱；60 秒后可以重新发送。",
        "masked_email": mask_email(email),
        "expires_in_seconds": settings.email_verification_code_minutes * 60,
        "retry_after_seconds": VERIFICATION_RESEND_COOLDOWN_SECONDS,
    }


@app.post("/api/v1/auth/forgot-password", response_model=AuthActionOut, status_code=202)
def forgot_password(data: EmailRequestIn, request: Request, db: Session = Depends(get_db)):
    ensure_public_origin(request)
    email = str(data.email).strip().lower()
    enforce_auth_rate_limit(db, request, "forgot_password", email)
    user = db.scalar(select(User).where(func.lower(User.email) == email, User.is_active.is_(True)))
    dev_action_url = None
    if user and user.email_verified_at is not None:
        dev_action_url = issue_auth_action(
            db, user, "reset_password", user.email, "/auth/reset-password", settings.password_reset_token_minutes,
        )
    return {"message": "如果邮箱已注册，密码重置邮件会发送到该邮箱。", "dev_action_url": dev_action_url}


@app.post("/api/v1/auth/reset-password", status_code=204)
def reset_password(data: PasswordResetIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ensure_public_origin(request)
    enforce_auth_rate_limit(db, request, "reset_password", token_hash(data.token))
    action_token = valid_auth_action(db, data.token, "reset_password")
    user = db.get(User, action_token.user_id)
    if not user or not user.is_active:
        raise HTTPException(400, "链接无效、已过期或已经使用")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user.password_hash = hash_password(data.new_password)
    db.execute(update(AuthActionToken).where(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == "reset_password",
        AuthActionToken.used_at.is_(None),
    ).values(used_at=now))
    db.execute(update(AuthSession).where(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).values(revoked_at=now, revoked_reason="password_reset"))
    db.commit()
    clear_auth_cookies(response)


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
    if not user or not user.is_active or user.email_verified_at is None:
        raise HTTPException(status_code=401, detail="账号不可用")
    set_auth_cookies(response, user, request, db, auth_session)
    return user


@app.post("/api/v1/auth/logout", status_code=204)
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    _, refresh_cookie = _cookie_names()
    refresh_token = request.cookies.get(refresh_cookie)
    if refresh_token:
        auth_session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(refresh_token)))
    else:
        auth_session = None
        access_token = request.cookies.get("__Host-access_token") or request.cookies.get("access_token")
        if access_token:
            try:
                payload = decode_access_token(access_token)
                auth_session = db.scalar(select(AuthSession).where(
                    AuthSession.id == int(payload["sid"]),
                    AuthSession.user_id == int(payload["sub"]),
                ))
            except Exception:
                auth_session = None
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


@app.patch("/api/v1/auth/me/email", response_model=AuthActionOut, status_code=202)
@app.post("/api/v1/auth/change-email", response_model=AuthActionOut, status_code=202)
def change_email(data: EmailChangeIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    enforce_auth_rate_limit(db, request, "change_email", str(user.id))
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "密码不正确")
    email = str(data.email).strip().lower()
    if email == user.email.lower():
        raise HTTPException(422, "新邮箱不能与当前邮箱相同")
    existing = db.scalar(select(User).where(User.email == email, User.id != user.id))
    if existing:
        raise HTTPException(409, "邮箱已经被使用")
    dev_action_url = issue_auth_action(
        db, user, "change_email", email, "/auth/confirm-email-change", settings.auth_email_token_minutes,
    )
    return {"message": "确认邮件已发送，新邮箱将在确认后生效。", "dev_action_url": dev_action_url}


@app.post("/api/v1/auth/change-email/confirm", response_model=AuthActionOut)
def confirm_email_change(data: AuthTokenIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ensure_public_origin(request)
    enforce_auth_rate_limit(db, request, "confirm_email_change", token_hash(data.token))
    action_token = valid_auth_action(db, data.token, "change_email")
    user = db.get(User, action_token.user_id)
    target_email = (action_token.target_email or "").strip().lower()
    if not user or not user.is_active or not target_email:
        raise HTTPException(400, "链接无效、已过期或已经使用")
    existing = db.scalar(select(User).where(func.lower(User.email) == target_email, User.id != user.id))
    if existing:
        raise HTTPException(409, "邮箱已经被使用，请重新申请修改")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user.email = target_email
    user.email_verified_at = now
    db.execute(update(AuthActionToken).where(
        AuthActionToken.user_id == user.id,
        AuthActionToken.purpose == "change_email",
        AuthActionToken.used_at.is_(None),
    ).values(used_at=now))
    db.execute(update(AuthSession).where(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).values(revoked_at=now, revoked_reason="email_changed"))
    db.commit()
    clear_auth_cookies(response)
    return {"message": "新邮箱已确认，请使用新邮箱重新登录。"}


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
    db.execute(update(ShareLink).where(
        ShareLink.itinerary_id.in_(select(Itinerary.id).where(Itinerary.user_id == user.id)),
        ShareLink.revoked_at.is_(None),
    ).values(revoked_at=now))
    user.public_id = None
    user.is_active = False
    user.deleted_at = now
    db.commit()
    clear_auth_cookies(response)


@app.get("/api/v1/auth/csrf")
def csrf(request: Request, response: Response, db: Session = Depends(get_db)):
    token = new_csrf_token()
    auth_session = None
    access_token = request.cookies.get("__Host-access_token") or request.cookies.get("access_token")
    if access_token:
        try:
            payload = decode_access_token(access_token)
            auth_session = db.scalar(select(AuthSession).where(
                AuthSession.id == int(payload["sid"]),
                AuthSession.user_id == int(payload["sub"]),
                AuthSession.revoked_at.is_(None),
            ))
        except Exception:
            auth_session = None
    if auth_session is None:
        _, refresh_cookie = _cookie_names()
        refresh_token = request.cookies.get(refresh_cookie)
        if refresh_token:
            auth_session = db.scalar(select(AuthSession).where(
                AuthSession.refresh_token_hash == token_hash(refresh_token),
                AuthSession.revoked_at.is_(None),
            ))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if auth_session and auth_session.expires_at > now:
        auth_session.csrf_token_hash = token_hash(token)
        db.commit()
    response.set_cookie("csrf_token", token, httponly=False, secure=settings.app_base_url.startswith("https://"), samesite="lax", path="/")
    return {"csrf_token": token}


@app.get("/api/v1/cities", response_model=list[CityOut])
def list_cities(db: Session = Depends(get_db)):
    return list(db.scalars(select(City).where(City.is_active.is_(True)).order_by(City.id)))


@app.get("/api/v1/cities/search", response_model=list[CityOut])
def search_cities(q: str = Query(default="", min_length=0, max_length=80), db: Session = Depends(get_db)):
    keyword = q.strip()
    if not keyword:
        return list(db.scalars(select(City).where(City.is_active.is_(True)).order_by(City.id)))
    return list(db.scalars(select(City).where(
        City.is_active.is_(True),
        (City.name.contains(keyword)) | (City.slug.contains(keyword))
    ).order_by(City.id)))


@app.get("/api/v1/cities/{city_id}", response_model=CityOut)
def get_city(city_id: int, db: Session = Depends(get_db)):
    city = db.get(City, city_id)
    if not city or not city.is_active:
        raise HTTPException(404, "城市不存在")
    return city


@app.get("/api/v1/cities/{city_id}/attractions", response_model=list[AttractionOut])
def city_attractions(city_id: int, db: Session = Depends(get_db)):
    city = db.get(City, city_id)
    if not city or not city.is_active:
        raise HTTPException(404, "城市不存在")
    attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city_id, Attraction.is_active.is_(True))))
    return sorted(attractions, key=lambda item: (-attraction_hot_score(db, item), item.id))


@app.get("/api/v1/attractions/search", response_model=list[AttractionOut])
def search_attractions(q: str = Query(default="", min_length=0, max_length=80), db: Session = Depends(get_db)):
    keyword = q.strip()
    if not keyword:
        return []
    return list(db.scalars(
        select(Attraction)
        .join(City, Attraction.city_id == City.id)
        .where(
            Attraction.is_active.is_(True),
            City.is_active.is_(True),
            or_(
                Attraction.name.contains(keyword),
                Attraction.description.contains(keyword),
                Attraction.area.contains(keyword),
                City.name.contains(keyword),
            ),
        )
        .order_by(Attraction.id)
        .limit(10)
    ))


@app.get("/api/v1/attractions/{attraction_id}", response_model=AttractionOut)
def get_attraction(attraction_id: int, db: Session = Depends(get_db)):
    attraction = db.get(Attraction, attraction_id)
    city = db.get(City, attraction.city_id) if attraction else None
    if not attraction or not attraction.is_active or not city or not city.is_active:
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
    query = select(MediaAsset).join(City, City.id == MediaAsset.city_id).where(City.is_active.is_(True))
    if city_id is not None:
        query = query.where(MediaAsset.city_id == city_id)
    if attraction_id is not None:
        query = query.where(MediaAsset.attraction_id == attraction_id)
    if purpose:
        query = query.where(MediaAsset.purpose == purpose)
    if not include_inactive:
        query = query.where(MediaAsset.is_active.is_(True))
    query = query.where(or_(MediaAsset.attraction_id.is_(None), MediaAsset.attraction_id.in_(
        select(Attraction.id).where(Attraction.is_active.is_(True))
    )))
    return list(db.scalars(query.order_by(MediaAsset.city_id, MediaAsset.attraction_id, MediaAsset.id)))


@app.get("/api/v1/admin/media-assets", response_model=list[MediaAssetOut])
def admin_list_media_assets(
    city_id: int | None = Query(default=None, ge=1),
    verification_status: str | None = Query(default=None, max_length=30),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    query = select(MediaAsset)
    if city_id is not None:
        query = query.where(MediaAsset.city_id == city_id)
    if verification_status:
        query = query.where(MediaAsset.verification_status == verification_status)
    return list(db.scalars(query.order_by(MediaAsset.city_id, MediaAsset.attraction_id, MediaAsset.id)))


@app.post("/api/v1/admin/media-assets/{asset_id}/autofill", response_model=MediaAssetOut)
def autofill_media_asset(asset_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(404, "图片记录不存在")
    if asset.is_active:
        raise HTTPException(409, "已启用的图片请先在编辑面板中手动替换，避免自动搜索中断当前展示")
    city = db.get(City, asset.city_id)
    attraction = db.get(Attraction, asset.attraction_id) if asset.attraction_id else None
    if not city:
        raise HTTPException(409, "图片所属城市不存在")
    search_term = attraction.name if attraction else city.name
    candidates = collect_photo_candidates(search_term, limit=1, city=city.name)
    candidate = candidates[0] if candidates else None
    if not candidate:
        raise HTTPException(404, "未找到可用候选图片，请手动填写图片地址或上传本地图片")
    asset.storage_type = "remote_url"
    asset.url = candidate["url"]
    asset.storage_path = None
    asset.mime_type = candidate["mime_type"]
    asset.alt_text = candidate["alt_text"]
    asset.source_name = candidate["source_name"]
    asset.source_author = candidate["source_author"]
    asset.license_name = candidate["license_name"]
    asset.attribution_url = candidate["attribution_url"]
    asset.verification_status = "needs_review"
    asset.is_active = False
    sync_media_display_target(db, asset)
    record_admin_audit(db, user, "autofill", "media_asset", asset.id, f"自动查找图片候选：{asset.content_key}")
    db.commit()
    db.refresh(asset)
    return asset


@app.patch("/api/v1/admin/media-assets/actions/bulk")
def bulk_update_media_assets(data: MediaAssetBulkUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    assets = list(db.scalars(select(MediaAsset).where(MediaAsset.id.in_(set(data.asset_ids)))))
    if len(assets) != len(set(data.asset_ids)):
        raise HTTPException(404, "部分图片记录不存在")
    if data.is_active and data.verification_status not in (None, "approved") and any(asset.verification_status != "approved" for asset in assets):
        raise HTTPException(422, "只能启用已核验图片")
    for asset in assets:
        if data.verification_status is not None:
            asset.verification_status = data.verification_status
        if data.is_active is not None:
            asset.is_active = data.is_active
        sync_media_display_target(db, asset)
    record_admin_audit(db, user, "bulk_update", "media_asset", None, f"批量更新 {len(assets)} 张图片", {"fields": sorted(data.model_fields_set)})
    db.commit()
    return {"updated": len(assets)}


@app.patch("/api/v1/admin/media-assets/{asset_id}", response_model=MediaAssetOut)
def update_media_asset(asset_id: int, data: MediaAssetUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(404, "图片记录不存在")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(asset, field, value)
    if asset.storage_type == "remote_url" and not asset.url:
        raise HTTPException(422, "远程图片必须填写图片地址")
    if asset.storage_type == "local_file":
        if not asset.storage_path or asset.storage_path.startswith(("/", "\\")) or ".." in Path(asset.storage_path).parts:
            raise HTTPException(422, "本地图片路径必须位于 backend/media 目录内")
        asset.url = media_display_url(asset)
    if asset.is_active and asset.verification_status != "approved":
        raise HTTPException(422, "只有已核验图片才能启用展示")
    sync_media_display_target(db, asset)
    record_admin_audit(db, user, "update", "media_asset", asset.id, f"修改图片记录：{asset.content_key}", {"fields": sorted(changes)})
    db.commit()
    db.refresh(asset)
    return asset


@app.post("/api/v1/admin/media-assets/{asset_id}/upload", response_model=MediaAssetOut)
async def upload_media_asset_file(
    asset_id: int,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    ensure_csrf(request)
    asset = db.get(MediaAsset, asset_id)
    if not asset:
        raise HTTPException(404, "图片记录不存在")
    if asset.is_active:
        raise HTTPException(409, "已启用的图片请先停用再上传替换，避免中断前台展示")
    city = db.get(City, asset.city_id)
    if not city:
        raise HTTPException(409, "图片所属城市不存在")
    attraction = db.get(Attraction, asset.attraction_id) if asset.attraction_id else None
    content = await file.read(8 * 1024 * 1024 + 1)
    try:
        cleaned, mime_type, suffix = sanitize_image_bytes(content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    relative_dir = f"attractions/{city.slug}/{attraction.id}/cover" if attraction else f"cities/{city.slug}/cover"
    file_name = f"{uuid.uuid4().hex}{suffix}"
    target = (MEDIA_ROOT / relative_dir / file_name).resolve()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(cleaned)
    except OSError as exc:
        raise HTTPException(500, "图片保存失败，请检查磁盘空间或目录权限") from exc
    if asset.storage_type == "local_file" and asset.storage_path:
        old = (MEDIA_ROOT / asset.storage_path).resolve()
        if old.is_file() and MEDIA_ROOT.resolve() in old.parents and old != target:
            try:
                old.unlink()
            except OSError:
                pass
    asset.storage_type = "local_file"
    asset.storage_path = f"{relative_dir}/{file_name}"
    asset.url = media_display_url(asset)
    asset.mime_type = mime_type
    asset.source_name = "本地导入"
    asset.source_author = None
    asset.license_name = None
    asset.attribution_url = None
    asset.verification_status = "needs_review"
    asset.is_active = False
    sync_media_display_target(db, asset)
    record_admin_audit(db, user, "upload", "media_asset", asset.id, f"上传本地图片：{asset.content_key}")
    db.commit()
    db.refresh(asset)
    return asset


def available_photo_providers() -> list[str]:
    """List the photo providers that the current configuration can actually use."""
    providers = ["Wikimedia Commons"]
    if settings.amap_web_service_key:
        providers.append("高德地图")
    if settings.unsplash_access_key:
        providers.append("Unsplash")
    if settings.pexels_api_key:
        providers.append("Pexels")
    return providers


@app.get("/api/v1/admin/photos", response_model=list[MediaAssetOut])
def admin_list_photos(
    city_id: int | None = Query(default=None, ge=1),
    attraction_id: int | None = Query(default=None, ge=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    query = select(MediaAsset).where(MediaAsset.purpose.like("photo-%"))
    if city_id is not None:
        query = query.where(MediaAsset.city_id == city_id)
    if attraction_id is not None:
        query = query.where(MediaAsset.attraction_id == attraction_id)
    return list(db.scalars(query.order_by(MediaAsset.id.desc())))


@app.get("/api/v1/admin/photos/providers")
def admin_photo_providers(user: User = Depends(current_user)):
    require_admin(user)
    return {"providers": available_photo_providers(), "download_enabled": settings.photo_download_enabled}


@app.post("/api/v1/admin/photos/fetch", response_model=AdminPhotoFetchOut)
def fetch_admin_photos(data: AdminPhotoFetchIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    city = db.get(City, data.city_id)
    if not city:
        raise HTTPException(404, "城市不存在")
    attraction = None
    if data.attraction_id is not None:
        attraction = db.get(Attraction, data.attraction_id)
        if not attraction or attraction.city_id != data.city_id:
            raise HTTPException(409, "景点不存在或不属于该城市")

    candidates = collect_photo_candidates(data.keyword, limit=data.limit, city=city.name)
    if not candidates:
        raise HTTPException(404, "未找到可用图片，请换个关键词或稍后再试")

    scope = [MediaAsset.city_id == data.city_id, MediaAsset.purpose.like("photo-%")]
    scope.append(MediaAsset.attraction_id.is_(None) if data.attraction_id is None else MediaAsset.attraction_id == data.attraction_id)
    existing_urls = set(db.scalars(select(MediaAsset.url).where(*scope)))
    used_purposes = set(db.scalars(select(MediaAsset.purpose).where(*scope)))

    relative_dir = f"attractions/{city.slug}/{attraction.id}/photos" if attraction else f"cities/{city.slug}/photos"
    file_prefix = attraction.name if attraction else city.name
    saved: list[MediaAsset] = []
    skipped = 0
    sequence = len(used_purposes)

    for candidate in candidates:
        if candidate["url"] in existing_urls:
            skipped += 1
            continue
        sequence += 1
        purpose = f"photo-{sequence}"
        while purpose in used_purposes:
            sequence += 1
            purpose = f"photo-{sequence}"
        used_purposes.add(purpose)
        existing_urls.add(candidate["url"])
        asset = MediaAsset(
            city_id=data.city_id,
            attraction_id=data.attraction_id,
            purpose=purpose,
            content_key=f"photo-{city.slug}-{attraction.id if attraction else 0}-{sequence}",
            storage_type="remote_url",
            url=candidate["url"],
            mime_type=candidate.get("mime_type"),
            alt_text=(candidate.get("alt_text") or data.keyword)[:240],
            source_name=candidate.get("source_name"),
            source_author=candidate.get("source_author"),
            license_name=candidate.get("license_name"),
            attribution_url=candidate.get("attribution_url"),
            verification_status="approved" if data.auto_approve else "needs_review",
            is_active=data.auto_approve,
        )
        if settings.photo_download_enabled:
            storage_path = download_image(candidate["url"], MEDIA_ROOT, relative_dir, f"{file_prefix}-{sequence}", candidate.get("mime_type"))
            if storage_path:
                asset.storage_type = "local_file"
                asset.storage_path = storage_path
                asset.url = media_display_url(asset)
        db.add(asset)
        saved.append(asset)

    if not saved:
        raise HTTPException(409, "这些图片已经抓取过了，请换个关键词")
    record_admin_audit(db, user, "fetch", "media_asset", None, f"自动抓取相片：{data.keyword}，新增 {len(saved)} 张")
    db.commit()
    for asset in saved:
        db.refresh(asset)
    return {"keyword": data.keyword, "fetched": len(saved), "skipped": skipped, "providers": available_photo_providers(), "items": saved}


@app.delete("/api/v1/admin/photos/{asset_id}", status_code=204)
def admin_delete_photo(asset_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    asset = db.get(MediaAsset, asset_id)
    if not asset or not asset.purpose.startswith("photo-"):
        raise HTTPException(404, "相片不存在")
    if asset.storage_type == "local_file" and asset.storage_path:
        target = (MEDIA_ROOT / asset.storage_path).resolve()
        if target.is_file() and MEDIA_ROOT.resolve() in target.parents:
            try:
                target.unlink()
            except OSError:
                pass
    record_admin_audit(db, user, "delete", "media_asset", asset.id, f"删除相片：{asset.content_key}")
    db.delete(asset)
    db.commit()


@app.post("/api/v1/admin/photos/{photo_id}/use-as-cover", response_model=MediaAssetOut)
def use_photo_as_cover(photo_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    photo = db.get(MediaAsset, photo_id)
    if not photo or not photo.purpose.startswith("photo-"):
        raise HTTPException(404, "相片不存在")
    city = db.get(City, photo.city_id)
    if not city:
        raise HTTPException(409, "相片所属城市不存在")
    attraction = db.get(Attraction, photo.attraction_id) if photo.attraction_id else None
    purpose = "attraction_cover" if attraction else "city_cover"
    cover = db.scalar(select(MediaAsset).where(
        MediaAsset.city_id == photo.city_id,
        MediaAsset.attraction_id == photo.attraction_id,
        MediaAsset.purpose == purpose,
    ))
    if cover is None:
        cover = MediaAsset(
            city_id=photo.city_id,
            attraction_id=photo.attraction_id,
            purpose=purpose,
            content_key=f"{city.slug}:attraction:{attraction.id}:cover" if attraction else f"{city.slug}:city:cover",
            storage_type=photo.storage_type,
            url=photo.url,
            storage_path=photo.storage_path,
            mime_type=photo.mime_type,
            alt_text=photo.alt_text,
            source_name=photo.source_name,
            source_author=photo.source_author,
            license_name=photo.license_name,
            attribution_url=photo.attribution_url,
            verification_status="needs_review",
            is_active=False,
        )
        db.add(cover)
    else:
        if cover.is_active:
            raise HTTPException(409, "该封面正在展示，请先在图片管理中停用，再设为封面")
        for field in ("storage_type", "url", "storage_path", "mime_type", "alt_text", "source_name", "source_author", "license_name", "attribution_url"):
            setattr(cover, field, getattr(photo, field))
        cover.verification_status = "needs_review"
        cover.is_active = False
    sync_media_display_target(db, cover)
    target_label = attraction.name if attraction else city.name
    record_admin_audit(db, user, "set_cover", "media_asset", cover.id, f"相片设为封面：{target_label} · {purpose}")
    db.commit()
    db.refresh(cover)
    return cover


def admin_city_dict(db: Session, city: City) -> dict:
    return {
        "id": city.id, "slug": city.slug, "name": city.name, "aliases": city.aliases or [],
        "description": city.description, "season": city.season, "budget": city.budget,
        "recommended_days": city.recommended_days, "image_url": city.image_url,
        "support_level": city.support_level, "planning_enabled": city.planning_enabled, "is_active": city.is_active,
        "attraction_count": db.scalar(select(func.count(Attraction.id)).where(Attraction.city_id == city.id)) or 0,
    }


def admin_attraction_dict(db: Session, attraction: Attraction) -> dict:
    city = db.get(City, attraction.city_id)
    return {
        "id": attraction.id, "city_id": attraction.city_id, "city_name": city.name if city else "已删除城市",
        "name": attraction.name, "description": attraction.description, "tags": attraction.tags or [],
        "opening_hours": attraction.opening_hours, "ticket_price": attraction.ticket_price,
        "duration_minutes": attraction.duration_minutes, "area": attraction.area,
        "latitude": attraction.latitude, "longitude": attraction.longitude, "image_url": attraction.image_url,
        "source": attraction.source, "is_active": attraction.is_active,
    }


@app.get("/api/v1/admin/cities", response_model=list[AdminCityOut])
def admin_list_cities(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    return [admin_city_dict(db, city) for city in db.scalars(select(City).order_by(City.id))]


@app.post("/api/v1/admin/cities", response_model=AdminCityOut, status_code=201)
def admin_create_city(data: AdminCityCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    city = City(**data.model_dump())
    db.add(city)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "城市英文标识已存在") from exc
    record_admin_audit(db, user, "create", "city", city.id, f"新增城市：{city.name}", {"slug": city.slug})
    db.commit()
    db.refresh(city)
    return admin_city_dict(db, city)


@app.patch("/api/v1/admin/cities/{city_id}", response_model=AdminCityOut)
def admin_update_city(city_id: int, data: AdminCityUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    city = db.get(City, city_id)
    if not city:
        raise HTTPException(404, "城市不存在")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(city, field, value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "城市英文标识已存在") from exc
    record_admin_audit(db, user, "update", "city", city.id, f"修改城市：{city.name}", {"fields": sorted(changes)})
    db.commit()
    db.refresh(city)
    return admin_city_dict(db, city)


@app.delete("/api/v1/admin/cities/{city_id}", status_code=204)
def admin_delete_city(city_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    city = db.get(City, city_id)
    if not city:
        raise HTTPException(404, "城市不存在")
    if city.is_active:
        raise HTTPException(409, "请先停用城市，再执行彻底删除")
    references = {
        "景点": db.scalar(select(func.count(Attraction.id)).where(Attraction.city_id == city_id)) or 0,
        "图片": db.scalar(select(func.count(MediaAsset.id)).where(MediaAsset.city_id == city_id)) or 0,
        "排行": db.scalar(select(func.count(RankingEntry.id)).where(RankingEntry.city_id == city_id)) or 0,
        "收藏": db.scalar(select(func.count(Favorite.id)).where(Favorite.target_type == "city", Favorite.target_id == city_id)) or 0,
        "浏览记录": db.scalar(select(func.count(RecentView.id)).where(RecentView.target_type == "city", RecentView.target_id == city_id)) or 0,
    }
    linked = [name for name, count in references.items() if count]
    if linked:
        raise HTTPException(409, f"城市仍有关联数据（{'、'.join(linked)}），只能保持停用")
    name = city.name
    db.delete(city)
    record_admin_audit(db, user, "delete", "city", city_id, f"删除城市：{name}")
    db.commit()


@app.post("/api/v1/admin/cities/import")
def admin_import_cities(data: AdminCityImportIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    slugs = [item.slug for item in data.items]
    if len(slugs) != len(set(slugs)):
        raise HTTPException(422, "导入数据中存在重复的城市英文标识")
    existing = set(db.scalars(select(City.slug).where(City.slug.in_(slugs))))
    if existing:
        raise HTTPException(409, f"城市英文标识已存在：{', '.join(sorted(existing))}")
    cities = [City(**item.model_dump()) for item in data.items]
    db.add_all(cities)
    db.flush()
    record_admin_audit(db, user, "import", "city", None, f"批量导入城市：{len(cities)} 条", {"count": len(cities), "slugs": slugs})
    db.commit()
    return {"created": len(cities)}


@app.get("/api/v1/admin/attractions", response_model=list[AdminAttractionOut])
def admin_list_attractions(city_id: int | None = Query(default=None, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    statement = select(Attraction).order_by(Attraction.city_id, Attraction.id)
    if city_id is not None:
        statement = statement.where(Attraction.city_id == city_id)
    return [admin_attraction_dict(db, attraction) for attraction in db.scalars(statement)]


@app.post("/api/v1/admin/attractions", response_model=AdminAttractionOut, status_code=201)
def admin_create_attraction(data: AdminAttractionCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    if not db.get(City, data.city_id):
        raise HTTPException(422, "所属城市不存在")
    attraction = Attraction(**data.model_dump())
    db.add(attraction)
    db.flush()
    record_admin_audit(db, user, "create", "attraction", attraction.id, f"新增景点：{attraction.name}", {"city_id": attraction.city_id})
    db.commit()
    db.refresh(attraction)
    return admin_attraction_dict(db, attraction)


@app.patch("/api/v1/admin/attractions/{attraction_id}", response_model=AdminAttractionOut)
def admin_update_attraction(attraction_id: int, data: AdminAttractionUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    attraction = db.get(Attraction, attraction_id)
    if not attraction:
        raise HTTPException(404, "景点不存在")
    changes = data.model_dump(exclude_unset=True)
    if "city_id" in changes and not db.get(City, changes["city_id"]):
        raise HTTPException(422, "所属城市不存在")
    for field, value in changes.items():
        setattr(attraction, field, value)
    record_admin_audit(db, user, "update", "attraction", attraction.id, f"修改景点：{attraction.name}", {"fields": sorted(changes)})
    db.commit()
    db.refresh(attraction)
    return admin_attraction_dict(db, attraction)


@app.delete("/api/v1/admin/attractions/{attraction_id}", status_code=204)
def admin_delete_attraction(attraction_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    attraction = db.get(Attraction, attraction_id)
    if not attraction:
        raise HTTPException(404, "景点不存在")
    if attraction.is_active:
        raise HTTPException(409, "请先停用景点，再执行彻底删除")
    references = {
        "行程": db.scalar(select(func.count(ItineraryStop.id)).where(ItineraryStop.attraction_id == attraction_id)) or 0,
        "图片": db.scalar(select(func.count(MediaAsset.id)).where(MediaAsset.attraction_id == attraction_id)) or 0,
        "排行": db.scalar(select(func.count(RankingEntry.id)).where(RankingEntry.attraction_id == attraction_id)) or 0,
        "收藏": db.scalar(select(func.count(Favorite.id)).where(Favorite.target_type == "attraction", Favorite.target_id == attraction_id)) or 0,
        "浏览记录": db.scalar(select(func.count(RecentView.id)).where(RecentView.target_type == "attraction", RecentView.target_id == attraction_id)) or 0,
    }
    linked = [name for name, count in references.items() if count]
    if linked:
        raise HTTPException(409, f"景点仍有关联数据（{'、'.join(linked)}），只能保持停用")
    name = attraction.name
    db.delete(attraction)
    record_admin_audit(db, user, "delete", "attraction", attraction_id, f"删除景点：{name}")
    db.commit()


@app.post("/api/v1/admin/attractions/import")
def admin_import_attractions(data: AdminAttractionImportIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    city_ids = {item.city_id for item in data.items}
    existing_ids = set(db.scalars(select(City.id).where(City.id.in_(city_ids))))
    if city_ids != existing_ids:
        raise HTTPException(422, "导入数据中存在不存在的所属城市")
    attractions = [Attraction(**item.model_dump()) for item in data.items]
    db.add_all(attractions)
    db.flush()
    record_admin_audit(db, user, "import", "attraction", None, f"批量导入景点：{len(attractions)} 条", {"count": len(attractions), "city_ids": sorted(city_ids)})
    db.commit()
    return {"created": len(attractions)}


def ranking_target(db: Session, ranking_type: str, city_id: int | None, attraction_id: int | None) -> tuple[int | None, int | None, str]:
    if ranking_type == "city":
        if city_id is None or attraction_id is not None:
            raise HTTPException(422, "城市排行必须只选择城市")
        city = db.get(City, city_id)
        if not city or not city.is_active:
            raise HTTPException(422, "排行城市不存在或已停用")
        return city.id, None, city.name
    if attraction_id is None or city_id is not None:
        raise HTTPException(422, "景点排行必须只选择景点")
    attraction = db.get(Attraction, attraction_id)
    city = db.get(City, attraction.city_id) if attraction else None
    if not attraction or not attraction.is_active or not city or not city.is_active:
        raise HTTPException(422, "排行景点不存在或已停用")
    return attraction.city_id, attraction.id, attraction.name


def ensure_ranking_conflicts_absent(
    db: Session,
    ranking_type: str,
    city_id: int | None,
    attraction_id: int | None,
    rank: int,
    is_active: bool,
    exclude_id: int | None = None,
) -> None:
    target_filter = RankingEntry.city_id == city_id if ranking_type == "city" else RankingEntry.attraction_id == attraction_id
    target_query = select(RankingEntry.id).where(RankingEntry.ranking_type == ranking_type, target_filter)
    if exclude_id is not None:
        target_query = target_query.where(RankingEntry.id != exclude_id)
    if db.scalar(target_query):
        raise HTTPException(409, "该对象已有排行记录，请直接编辑")
    if not is_active:
        return
    rank_query = select(RankingEntry.id).where(
        RankingEntry.ranking_type == ranking_type,
        RankingEntry.rank == rank,
        RankingEntry.is_active.is_(True),
    )
    if exclude_id is not None:
        rank_query = rank_query.where(RankingEntry.id != exclude_id)
    if db.scalar(rank_query):
        raise HTTPException(409, f"第 {rank} 名已被其他展示中的记录占用")


def admin_ranking_dict(db: Session, entry: RankingEntry) -> dict:
    target = db.get(City, entry.city_id) if entry.ranking_type == "city" else db.get(Attraction, entry.attraction_id)
    return {"id": entry.id, "ranking_type": entry.ranking_type, "city_id": entry.city_id, "attraction_id": entry.attraction_id, "target_name": target.name if target else "已删除对象", "rank": entry.rank, "score": entry.score, "reason": entry.reason, "is_active": entry.is_active, "created_at": entry.created_at, "updated_at": entry.updated_at}


@app.get("/api/v1/admin/rankings", response_model=list[AdminRankingOut])
def admin_list_rankings(ranking_type: str | None = Query(default=None, pattern="^(city|attraction)$"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    statement = select(RankingEntry).order_by(RankingEntry.ranking_type, RankingEntry.rank, RankingEntry.id)
    if ranking_type:
        statement = statement.where(RankingEntry.ranking_type == ranking_type)
    return [admin_ranking_dict(db, entry) for entry in db.scalars(statement)]


@app.post("/api/v1/admin/rankings", response_model=AdminRankingOut, status_code=201)
def admin_create_ranking(data: AdminRankingCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    city_id, attraction_id, target_name = ranking_target(db, data.ranking_type, data.city_id, data.attraction_id)
    ensure_ranking_conflicts_absent(db, data.ranking_type, city_id, attraction_id, data.rank, data.is_active)
    entry_payload = data.model_dump()
    entry_payload["city_id"] = city_id
    entry_payload["attraction_id"] = attraction_id
    entry = RankingEntry(**entry_payload)
    db.add(entry)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "该对象已有排行记录，请直接编辑") from exc
    record_admin_audit(db, user, "create", "ranking", entry.id, f"新增{data.ranking_type}排行：{target_name}", {"rank": entry.rank})
    db.commit()
    db.refresh(entry)
    return admin_ranking_dict(db, entry)


@app.patch("/api/v1/admin/rankings/{entry_id}", response_model=AdminRankingOut)
def admin_update_ranking(entry_id: int, data: AdminRankingUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    entry = db.get(RankingEntry, entry_id)
    if not entry:
        raise HTTPException(404, "排行记录不存在")
    changes = data.model_dump(exclude_unset=True)
    ensure_ranking_conflicts_absent(
        db,
        entry.ranking_type,
        entry.city_id,
        entry.attraction_id,
        changes.get("rank", entry.rank),
        changes.get("is_active", entry.is_active),
        exclude_id=entry.id,
    )
    for field, value in changes.items():
        setattr(entry, field, value)
    record_admin_audit(db, user, "update", "ranking", entry.id, "修改排行记录", {"fields": sorted(changes)})
    db.commit()
    db.refresh(entry)
    return admin_ranking_dict(db, entry)


@app.delete("/api/v1/admin/rankings/{entry_id}", status_code=204)
def admin_delete_ranking(entry_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    entry = db.get(RankingEntry, entry_id)
    if not entry:
        raise HTTPException(404, "排行记录不存在")
    target_name = admin_ranking_dict(db, entry)["target_name"]
    db.delete(entry)
    record_admin_audit(db, user, "delete", "ranking", entry_id, f"删除排行记录：{target_name}")
    db.commit()


@app.post("/api/v1/admin/rankings/import")
def admin_import_rankings(data: AdminRankingImportIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    entries = []
    seen_targets: set[tuple[str, int | None, int | None]] = set()
    seen_active_ranks: set[tuple[str, int]] = set()
    for item in data.items:
        city_id, attraction_id, _ = ranking_target(db, item.ranking_type, item.city_id, item.attraction_id)
        key = (item.ranking_type, city_id if item.ranking_type == "city" else None, attraction_id)
        if key in seen_targets:
            raise HTTPException(422, "导入数据中存在重复排行对象")
        seen_targets.add(key)
        active_rank_key = (item.ranking_type, item.rank)
        if item.is_active and active_rank_key in seen_active_ranks:
            raise HTTPException(422, f"导入数据中存在重复的展示名次：{item.ranking_type} 第 {item.rank} 名")
        if item.is_active:
            seen_active_ranks.add(active_rank_key)
        ensure_ranking_conflicts_absent(db, item.ranking_type, city_id, attraction_id, item.rank, item.is_active)
        entry_payload = item.model_dump()
        entry_payload["city_id"] = city_id
        entry_payload["attraction_id"] = attraction_id
        entries.append(RankingEntry(**entry_payload))
    db.add_all(entries)
    db.flush()
    record_admin_audit(db, user, "import", "ranking", None, f"批量导入排行：{len(entries)} 条", {"count": len(entries)})
    db.commit()
    return {"created": len(entries)}


@app.get("/api/v1/admin/audit-logs", response_model=AdminAuditLogPageOut)
def admin_audit_logs(page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=10, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    total = db.scalar(select(func.count(AdminAuditLog.id))) or 0
    logs = db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [{"id": item.id, "actor_username": item.actor_username, "action": item.action, "target_type": item.target_type, "target_id": item.target_id, "summary": item.summary, "created_at": item.created_at} for item in logs], "total": total, "page": page, "page_size": page_size}


@app.get("/api/v1/rankings")
def rankings(type: str = "city", city_id: int | None = Query(default=None, ge=1), db: Session = Depends(get_db)):
    if type not in {"city", "attraction"}:
        raise HTTPException(status_code=400, detail="排行类型必须是 city 或 attraction")
    manual_query = select(RankingEntry).where(RankingEntry.ranking_type == type, RankingEntry.is_active.is_(True))
    if type == "attraction" and city_id is not None:
        city = db.get(City, city_id)
        if not city or not city.is_active:
            raise HTTPException(status_code=404, detail="城市不存在")
        manual_query = manual_query.where(RankingEntry.city_id == city_id)
    manual_entries = list(db.scalars(manual_query.order_by(RankingEntry.rank, RankingEntry.id)))
    if manual_entries:
        results = []
        for entry in manual_entries:
            target = db.get(City, entry.city_id) if entry.ranking_type == "city" else db.get(Attraction, entry.attraction_id)
            target_city = target if isinstance(target, City) else db.get(City, target.city_id) if target else None
            if target and target.is_active and target_city and target_city.is_active:
                results.append({"rank": entry.rank, "city_id": entry.city_id, "attraction_id": entry.attraction_id, "name": target.name, "score": entry.score, "reason": entry.reason, "data_source": "admin_curated"})
        return results
    if type == "city":
        cities = list(db.scalars(select(City).where(City.is_active.is_(True)).order_by(City.id)))
        return [{"rank": index + 1, "name": city.name, "score": 96 - index * 4, "reason": city.season} for index, city in enumerate(cities)]
    query = select(Attraction)
    if city_id is not None:
        city = db.get(City, city_id)
        if not city or not city.is_active:
            raise HTTPException(status_code=404, detail="城市不存在")
        query = query.where(Attraction.city_id == city_id)
    query = query.join(City, City.id == Attraction.city_id).where(Attraction.is_active.is_(True), City.is_active.is_(True))
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
BULK_SESSION_DELETE_PASSWORD_THRESHOLD = 3


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


@app.post("/api/v1/sessions/bulk")
def bulk_update_sessions(
    data: SessionBulkUpdateIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ensure_csrf(request)
    session_ids = list(dict.fromkeys(data.session_ids))
    if len(session_ids) != len(data.session_ids):
        raise HTTPException(422, "会话不能重复选择")
    sessions_to_update = list(db.scalars(
        select(ChatSession).where(
            ChatSession.id.in_(session_ids),
            ChatSession.user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
    ))
    if len(sessions_to_update) != len(session_ids):
        raise HTTPException(404, "会话不存在或无权操作")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if data.action == "delete":
        if len(sessions_to_update) >= BULK_SESSION_DELETE_PASSWORD_THRESHOLD:
            if not data.password or not verify_password(data.password, user.password_hash):
                raise HTTPException(403, "请验证当前账号密码后删除多条会话")
        active_job = db.scalar(select(PlanningJob.id).where(
            PlanningJob.session_id.in_(session_ids),
            PlanningJob.status.in_(["queued", "running"]),
        ))
        if active_job:
            raise HTTPException(409, "所选会话仍有任务正在处理，请先停止任务")
        for chat_session in sessions_to_update:
            chat_session.deleted_at = now
            chat_session.is_pinned = False
            chat_session.updated_at = now
    else:
        archived_at = now if data.action == "archive" else None
        for chat_session in sessions_to_update:
            chat_session.archived_at = archived_at
            if archived_at:
                chat_session.is_pinned = False
            chat_session.updated_at = now
    db.commit()
    return {"processed_count": len(sessions_to_update), "action": data.action}


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
    origin_city_id = allowed_patch.get("origin_city_id")
    if origin_city_id:
        origin_city = db.get(City, origin_city_id)
        if not origin_city or not origin_city.is_active:
            raise HTTPException(status_code=422, detail="所选出发城市不可用")
        allowed_patch["origin"] = origin_city.name
    destination_city_id = allowed_patch.get("destination_city_id")
    if destination_city_id:
        city = db.get(City, destination_city_id)
        if not city or not city.is_active or city.support_level != "full" or not city.planning_enabled:
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


def optional_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    try:
        return current_user(request, db)
    except HTTPException:
        return None


def public_itinerary_snapshot(db: Session, itinerary_id: int) -> dict:
    itinerary = itinerary_dict(db, itinerary_id) or {}
    return {
        "title": itinerary.get("title", ""),
        "city_name": itinerary.get("city_name", ""),
        "days": itinerary.get("days", 0),
        "budget_total": itinerary.get("budget_total", 0),
        "preferences": itinerary.get("preferences", []),
        "itinerary_days": [{
            "day_number": day.get("day_number"),
            "title": day.get("title", ""),
            "stops": [{
                "name": stop.get("name", ""),
                "start_time": stop.get("start_time", ""),
                "end_time": stop.get("end_time", ""),
            } for stop in day.get("stops", [])],
        } for day in itinerary.get("itinerary_days", [])],
    }


def community_author_name(db: Session, user_id: int) -> str:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    user = db.get(User, user_id)
    return (profile.display_name if profile and profile.display_name else user.username) if user else "旅行者"


def community_post_dict(db: Session, post: CommunityPost, viewer: User | None = None, include_comments: bool = False) -> dict:
    images = list(db.scalars(select(CommunityPostImage).where(
        CommunityPostImage.post_id == post.id,
        CommunityPostImage.status == "published",
    ).order_by(CommunityPostImage.sort_order)))
    comment_query = select(CommunityComment).where(
        CommunityComment.post_id == post.id,
        CommunityComment.status == "published",
    ).order_by(CommunityComment.created_at.asc(), CommunityComment.id.asc())
    comments = list(db.scalars(comment_query.limit(100))) if include_comments else []
    values = {
        "id": post.id,
        "title": post.title,
        "body": post.body,
        "city_name": post.city_name,
        "status": post.status,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
        "author": {"id": post.author_id, "name": community_author_name(db, post.author_id)},
        "itinerary": post.itinerary_snapshot,
        "images": [{"id": image.id, "url": f"/media/{image.storage_path}", "alt_text": image.alt_text} for image in images],
        "like_count": db.scalar(select(func.count(CommunityPostLike.id)).where(CommunityPostLike.post_id == post.id)) or 0,
        "favorite_count": db.scalar(select(func.count(CommunityPostFavorite.id)).where(CommunityPostFavorite.post_id == post.id)) or 0,
        "comment_count": db.scalar(select(func.count(CommunityComment.id)).where(CommunityComment.post_id == post.id, CommunityComment.status == "published")) or 0,
        "liked": bool(viewer and db.scalar(select(CommunityPostLike.id).where(CommunityPostLike.post_id == post.id, CommunityPostLike.user_id == viewer.id))),
        "favorited": bool(viewer and db.scalar(select(CommunityPostFavorite.id).where(CommunityPostFavorite.post_id == post.id, CommunityPostFavorite.user_id == viewer.id))),
        "can_manage": bool(viewer and (viewer.id == post.author_id or viewer.role == "admin")),
    }
    if include_comments:
        values["comments"] = [{
            "id": comment.id,
            "body": comment.body,
            "created_at": comment.created_at,
            "author": {"id": comment.author_id, "name": community_author_name(db, comment.author_id)},
            "can_manage": bool(viewer and (viewer.id == comment.author_id or viewer.role == "admin")),
        } for comment in comments]
    return values


def published_community_post(db: Session, post_id: int) -> CommunityPost:
    post = db.get(CommunityPost, post_id)
    if not post or post.status != "published":
        raise HTTPException(404, "社区帖子不存在")
    return post


@app.get("/api/v1/community/posts")
def list_community_posts(
    city: str = Query(default="", max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=12, ge=1, le=24),
    viewer: User | None = Depends(optional_current_user),
    db: Session = Depends(get_db),
):
    filters = [CommunityPost.status == "published"]
    if city.strip():
        filters.append(CommunityPost.city_name == city.strip())
    total = db.scalar(select(func.count(CommunityPost.id)).where(*filters)) or 0
    posts = list(db.scalars(select(CommunityPost).where(*filters).order_by(
        CommunityPost.created_at.desc(), CommunityPost.id.desc()
    ).offset((page - 1) * page_size).limit(page_size)))
    return {"items": [community_post_dict(db, post, viewer) for post in posts], "total": total, "page": page, "page_size": page_size}


@app.get("/api/v1/community/posts/{post_id}")
def get_community_post(post_id: int, viewer: User | None = Depends(optional_current_user), db: Session = Depends(get_db)):
    return community_post_dict(db, published_community_post(db, post_id), viewer, include_comments=True)


@app.get("/api/v1/community/me/posts")
def list_my_community_posts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    posts = db.scalars(select(CommunityPost).where(CommunityPost.author_id == user.id).order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc()))
    return [community_post_dict(db, post, user) for post in posts]


@app.post("/api/v1/community/posts", status_code=201)
def create_community_post(data: CommunityPostCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary = itinerary_for_user(data.itinerary_id, user, db)
    if itinerary.status != "saved":
        raise HTTPException(409, "请先保存行程再发布到社区")
    post = CommunityPost(
        author_id=user.id,
        itinerary_id=itinerary.id,
        itinerary_snapshot=public_itinerary_snapshot(db, itinerary.id),
        city_name=itinerary.city_name,
        title=data.title.strip(),
        body=data.body.strip(),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return community_post_dict(db, post, user)


@app.patch("/api/v1/community/posts/{post_id}")
def update_community_post(post_id: int, data: CommunityPostUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    post = db.get(CommunityPost, post_id)
    if not post or post.author_id != user.id:
        raise HTTPException(404, "社区帖子不存在")
    post.title = data.title.strip()
    post.body = data.body.strip()
    db.commit()
    db.refresh(post)
    return community_post_dict(db, post, user)


@app.delete("/api/v1/community/posts/{post_id}", status_code=204)
def withdraw_community_post(post_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    post = db.get(CommunityPost, post_id)
    if not post or post.author_id != user.id:
        raise HTTPException(404, "社区帖子不存在")
    post.status = "hidden"
    db.commit()


def image_type_from_bytes(content: bytes) -> tuple[str, str] | None:
    if content.startswith(b"\xff\xd8\xff"):
        return ("image/jpeg", ".jpg")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ("image/png", ".png")
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ("image/webp", ".webp")
    return None


@app.post("/api/v1/community/posts/{post_id}/images")
async def upload_community_images(
    post_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    alt_texts: list[str] = Form(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    ensure_csrf(request)
    post = db.get(CommunityPost, post_id)
    if not post or post.author_id != user.id or post.status != "published":
        raise HTTPException(404, "社区帖子不存在")
    existing_count = db.scalar(select(func.count(CommunityPostImage.id)).where(CommunityPostImage.post_id == post_id)) or 0
    if not files or existing_count + len(files) > 9:
        raise HTTPException(422, "每篇帖子最多上传 9 张照片")
    saved_images = []
    community_root = MEDIA_ROOT / "community"
    community_root.mkdir(parents=True, exist_ok=True)
    for index, upload in enumerate(files):
        content = await upload.read(8 * 1024 * 1024 + 1)
        try:
            cleaned, mime_type, suffix = sanitize_image_bytes(content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        storage_path = f"community/{uuid.uuid4().hex}{suffix}"
        (MEDIA_ROOT / storage_path).write_bytes(cleaned)
        saved_images.append(CommunityPostImage(
            post_id=post_id,
            storage_path=storage_path,
            mime_type=mime_type,
            alt_text=(alt_texts[index].strip() if index < len(alt_texts) else "")[:240],
            sort_order=existing_count + index,
        ))
    db.add_all(saved_images)
    db.commit()
    return [{"id": image.id, "url": f"/media/{image.storage_path}", "alt_text": image.alt_text} for image in saved_images]


@app.put("/api/v1/community/posts/{post_id}/like")
def like_community_post(post_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    published_community_post(db, post_id)
    if not db.scalar(select(CommunityPostLike).where(CommunityPostLike.post_id == post_id, CommunityPostLike.user_id == user.id)):
        db.add(CommunityPostLike(post_id=post_id, user_id=user.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"ok": True}


@app.delete("/api/v1/community/posts/{post_id}/like", status_code=204)
def unlike_community_post(post_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    item = db.scalar(select(CommunityPostLike).where(CommunityPostLike.post_id == post_id, CommunityPostLike.user_id == user.id))
    if item:
        db.delete(item)
        db.commit()


@app.put("/api/v1/community/posts/{post_id}/favorite")
def favorite_community_post(post_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    published_community_post(db, post_id)
    if not db.scalar(select(CommunityPostFavorite).where(CommunityPostFavorite.post_id == post_id, CommunityPostFavorite.user_id == user.id)):
        db.add(CommunityPostFavorite(post_id=post_id, user_id=user.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"ok": True}


@app.delete("/api/v1/community/posts/{post_id}/favorite", status_code=204)
def unfavorite_community_post(post_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    item = db.scalar(select(CommunityPostFavorite).where(CommunityPostFavorite.post_id == post_id, CommunityPostFavorite.user_id == user.id))
    if item:
        db.delete(item)
        db.commit()


@app.post("/api/v1/community/posts/{post_id}/comments", status_code=201)
def create_community_comment(post_id: int, data: CommunityCommentCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    published_community_post(db, post_id)
    comment = CommunityComment(post_id=post_id, author_id=user.id, body=data.body.strip())
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {"id": comment.id, "body": comment.body, "created_at": comment.created_at, "author": {"id": user.id, "name": community_author_name(db, user.id)}, "can_manage": True}


@app.post("/api/v1/community/reports", status_code=201)
def create_content_report(data: ContentReportCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    models = {"post": CommunityPost, "comment": CommunityComment, "image": CommunityPostImage}
    if not db.get(models[data.target_type], data.target_id):
        raise HTTPException(404, "举报对象不存在")
    report = ContentReport(reporter_id=user.id, target_type=data.target_type, target_id=data.target_id, reason=data.reason.strip())
    db.add(report)
    db.commit()
    return {"id": report.id, "status": report.status}


@app.get("/api/v1/itineraries")
def list_itineraries(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [itinerary_dict(db, itinerary.id) for itinerary in db.scalars(select(Itinerary).where(Itinerary.user_id == user.id, Itinerary.deleted_at.is_(None)).order_by(Itinerary.id.desc()))]


@app.get("/api/v1/itineraries/{itinerary_id}")
def get_itinerary(itinerary_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    itinerary_for_user(itinerary_id, user, db)
    return itinerary_dict(db, itinerary_id)


@app.get("/api/v1/itineraries/{itinerary_id}/agent-run")
def latest_itinerary_agent_run(itinerary_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    itinerary_for_user(itinerary_id, user, db)
    run = db.scalar(select(AgentRun).where(AgentRun.itinerary_id == itinerary_id).order_by(AgentRun.id.desc()))
    if not run:
        raise HTTPException(404, "该行程没有可展示的 Agent 执行记录")
    calls = list(db.scalars(select(AgentToolCall).where(AgentToolCall.agent_run_id == run.id).order_by(AgentToolCall.sequence)))
    return {
        "id": run.id,
        "status": run.status,
        "algorithm_version": run.algorithm_version,
        "input": run.input_data,
        "summary": run.summary,
        "created_at": run.created_at,
        "steps": [{
            "sequence": call.sequence,
            "tool_name": call.tool_name,
            "input": call.input_data,
            "output": call.output_data,
            "status": call.status,
        } for call in calls],
    }


@app.patch("/api/v1/itineraries/{itinerary_id}")
def save_itinerary(itinerary_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary = itinerary_for_user(itinerary_id, user, db)
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
    if itinerary.deleted_at is not None:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    itinerary.deleted_at = now
    db.execute(update(ShareLink).where(
        ShareLink.itinerary_id == itinerary_id,
        ShareLink.revoked_at.is_(None),
    ).values(revoked_at=now))
    db.execute(update(PlanningJob).where(
        PlanningJob.result_itinerary_id == itinerary_id,
        PlanningJob.status.in_(["queued", "running"]),
    ).values(status="cancelled", stage="cancelled", error_message="关联行程已删除", updated_at=now))
    db.commit()


def itinerary_for_user(itinerary_id: int, user: User, db: Session) -> Itinerary:
    itinerary = db.get(Itinerary, itinerary_id)
    if not itinerary or itinerary.user_id != user.id or itinerary.deleted_at is not None:
        raise HTTPException(404, "行程不存在")
    return itinerary


def save_itinerary_revision(db: Session, itinerary_id: int, snapshot: dict, reason: str) -> None:
    latest = db.scalar(select(func.max(ItineraryRevision.version_no)).where(ItineraryRevision.itinerary_id == itinerary_id)) or 0
    db.add(ItineraryRevision(itinerary_id=itinerary_id, version_no=latest + 1, snapshot=snapshot, reason=reason))


def validate_itinerary_days(db: Session, itinerary: Itinerary, day_data: list[dict]) -> list[dict]:
    if not day_data:
        raise HTTPException(422, "行程至少需要保留一天")

    day_numbers = [item["day_number"] for item in day_data]
    if sorted(day_numbers) != list(range(1, len(day_data) + 1)):
        raise HTTPException(422, "行程日期编号必须从第 1 天连续排列")

    city = db.scalar(select(City).where(City.name == itinerary.city_name))
    if not city:
        raise HTTPException(409, "行程所属城市资料不存在，无法校验景点")

    attraction_ids = {
        stop["attraction_id"]
        for day in day_data
        for stop in day.get("stops", [])
        if stop.get("attraction_id") is not None
    }
    attractions = {
        attraction.id: attraction
        for attraction in db.scalars(select(Attraction).where(Attraction.id.in_(attraction_ids)))
    }
    used_attractions: set[int] = set()

    for day in day_data:
        intervals: list[tuple[datetime, datetime]] = []
        for stop in day.get("stops", []):
            attraction_id = stop.get("attraction_id")
            if attraction_id is not None:
                attraction = attractions.get(attraction_id)
                if not attraction or attraction.city_id != city.id:
                    raise HTTPException(422, f"景点不属于行程城市：{stop.get('name', '未命名景点')}")
                if attraction_id in used_attractions:
                    raise HTTPException(422, f"景点不能重复安排：{attraction.name}")
                used_attractions.add(attraction_id)
                # The database is the source of truth for names after ID validation.
                stop["name"] = attraction.name

            try:
                start = datetime.strptime(stop["start_time"], "%H:%M")
                end = datetime.strptime(stop["end_time"], "%H:%M")
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(422, "景点时间必须使用 HH:MM 格式") from exc
            if start >= end:
                raise HTTPException(422, "景点开始时间必须早于结束时间")
            if any(start < previous_end and previous_start < end for previous_start, previous_end in intervals):
                raise HTTPException(422, f"第 {day['day_number']} 天存在重叠的景点时间")
            intervals.append((start, end))
            stop["start_time"] = start.strftime("%H:%M")
            stop["end_time"] = end.strftime("%H:%M")

    return day_data


def replace_itinerary_days(db: Session, itinerary: Itinerary, day_data: list[dict]) -> None:
    day_data = validate_itinerary_days(db, itinerary, day_data)
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
    structured_actions = []
    if structured_actions:
        city = db.scalar(select(City).where(City.name == itinerary.city_name))
        if not city:
            raise HTTPException(409, "行程所属城市资料不存在，无法校验")
        for action in structured_actions:
            if action.type == "set_days":
                if action.value is None or not 1 <= action.value <= 10:
                    raise HTTPException(422, "set_days 必须提供 1 到 10 的 value")
                current_days = snapshot.get("itinerary_days", [])
                while len(current_days) < action.value:
                    number = len(current_days) + 1
                    current_days.append({"day_number": number, "title": f"第{number}天 · {itinerary.city_name}探索", "stops": []})
                snapshot["itinerary_days"] = current_days[:action.value]
            elif action.type == "set_budget":
                if action.value is None:
                    raise HTTPException(422, "set_budget 必须提供 value")
                snapshot["budget_total"] = action.value
            elif action.type == "remove_attraction":
                if action.attraction_id is None:
                    raise HTTPException(422, "remove_attraction 必须提供 attraction_id")
                found = False
                for day in snapshot.get("itinerary_days", []):
                    before = len(day.get("stops", []))
                    day["stops"] = [stop for stop in day.get("stops", []) if stop.get("attraction_id") != action.attraction_id]
                    found = found or len(day["stops"]) != before
                if not found:
                    raise HTTPException(422, "要删除的景点不在当前行程中")
            elif action.type == "replace_attraction":
                if action.attraction_id is None or action.new_attraction_id is None:
                    raise HTTPException(422, "replace_attraction 必须提供 attraction_id 和 new_attraction_id")
                replacement = db.get(Attraction, action.new_attraction_id)
                if not replacement or not replacement.is_active or replacement.city_id != city.id:
                    raise HTTPException(422, "替换景点必须属于当前行程城市")
                found = False
                for day in snapshot.get("itinerary_days", []):
                    for stop in day.get("stops", []):
                        if stop.get("attraction_id") == action.attraction_id:
                            stop["attraction_id"] = replacement.id
                            stop["name"] = replacement.name
                            stop["note"] = f"{replacement.area} · 建议游览{replacement.duration_minutes}分钟 · 开放时间{replacement.opening_hours}"
                            found = True
                if not found:
                    raise HTTPException(422, "要替换的景点不在当前行程中")
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
    if False:
        attraction_ids = {
            stop.get("attraction_id")
            for day in snapshot.get("itinerary_days", [])
            for stop in day.get("stops", [])
            if stop.get("attraction_id") is not None
        }
        total_ticket = sum(item.ticket_price for item in db.scalars(select(Attraction).where(Attraction.id.in_(attraction_ids))))
        if snapshot.get("budget_total") is not None and total_ticket > snapshot["budget_total"]:
            raise HTTPException(422, f"调整后门票估算 ¥{total_ticket} 超出预算 ¥{snapshot['budget_total']}")
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


def apply_structured_replan_actions(db: Session, itinerary: Itinerary, snapshot: dict, actions: list) -> None:
    """Execute schema-validated operations, then enforce the same database constraints as manual edits."""
    city = db.scalar(select(City).where(City.name == itinerary.city_name))
    if not city:
        raise HTTPException(409, "行程所属城市资料不存在，无法校验")
    for action in actions:
        if action.type == "set_days":
            if action.value is None or not 1 <= action.value <= 10:
                raise HTTPException(422, "set_days 必须提供 1 到 10 的 value")
            current_days = snapshot.get("itinerary_days", [])
            while len(current_days) < action.value:
                number = len(current_days) + 1
                current_days.append({"day_number": number, "title": f"第{number}天 · {itinerary.city_name}探索", "stops": []})
            snapshot["itinerary_days"] = current_days[:action.value]
        elif action.type == "set_budget":
            if action.value is None:
                raise HTTPException(422, "set_budget 必须提供 value")
            snapshot["budget_total"] = action.value
        elif action.type == "set_preferences":
            if action.preferences is None:
                raise HTTPException(422, "set_preferences 必须提供 preferences")
            snapshot["preferences"] = list(dict.fromkeys(item.strip() for item in action.preferences if item.strip()))
        elif action.type == "remove_attraction":
            if action.attraction_id is None:
                raise HTTPException(422, "remove_attraction 必须提供 attraction_id")
            found = False
            for day in snapshot.get("itinerary_days", []):
                before = len(day.get("stops", []))
                day["stops"] = [stop for stop in day.get("stops", []) if stop.get("attraction_id") != action.attraction_id]
                found = found or len(day["stops"]) != before
            if not found:
                raise HTTPException(422, "要删除的景点不在当前行程中")
        elif action.type == "replace_attraction":
            if action.attraction_id is None or action.new_attraction_id is None:
                raise HTTPException(422, "replace_attraction 必须提供 attraction_id 和 new_attraction_id")
            replacement = db.get(Attraction, action.new_attraction_id)
            if not replacement or not replacement.is_active or replacement.city_id != city.id:
                raise HTTPException(422, "替换景点必须属于当前行程城市")
            found = False
            for day in snapshot.get("itinerary_days", []):
                for stop in day.get("stops", []):
                    if stop.get("attraction_id") == action.attraction_id:
                        stop.update(attraction_id=replacement.id, name=replacement.name, note=f"{replacement.area} · 建议游览{replacement.duration_minutes}分钟 · 开放时间{replacement.opening_hours}")
                        found = True
            if not found:
                raise HTTPException(422, "要替换的景点不在当前行程中")
    attraction_ids = {stop.get("attraction_id") for day in snapshot.get("itinerary_days", []) for stop in day.get("stops", []) if stop.get("attraction_id") is not None}
    total_ticket = sum(item.ticket_price for item in db.scalars(select(Attraction).where(Attraction.id.in_(attraction_ids))))
    if snapshot.get("budget_total") is not None and total_ticket > snapshot["budget_total"]:
        raise HTTPException(422, f"调整后门票估算 ¥{total_ticket} 超出预算 ¥{snapshot['budget_total']}")


def replan_action_summary(actions: list[ReplanActionIn], attractions: dict[int, Attraction]) -> str:
    parts = []
    for action in actions:
        if action.type == "set_days":
            parts.append(f"调整为 {action.value} 天")
        elif action.type == "set_budget":
            parts.append(f"预算调整为 ¥{action.value}")
        elif action.type == "set_preferences":
            parts.append(f"偏好更新为 {'、'.join(action.preferences or []) or '无'}")
        elif action.type == "remove_attraction":
            parts.append(f"删除 {attractions.get(action.attraction_id).name if attractions.get(action.attraction_id) else '指定景点'}")
        elif action.type == "replace_attraction":
            source = attractions.get(action.attraction_id)
            target = attractions.get(action.new_attraction_id)
            parts.append(f"{source.name if source else '指定景点'} 替换为 {target.name if target else '指定景点'}")
    return "；".join(parts)


def local_replan_preview(instruction: str, snapshot: dict, attractions: list[Attraction]) -> tuple[list[ReplanActionIn], list[str]]:
    actions: list[ReplanActionIn] = []
    questions: list[str] = []
    current_stop_ids = {stop.get("attraction_id") for day in snapshot.get("itinerary_days", []) for stop in day.get("stops", [])}
    current_stops = [item for item in attractions if item.id in current_stop_ids]

    day_match = re.search(r"(?:改成|调整为|安排为|延长到|缩短到)\s*(\d+)\s*[天日]", instruction)
    if day_match:
        actions.append(ReplanActionIn(type="set_days", value=max(1, min(int(day_match.group(1)), 10))))

    budget_match = re.search(r"(?:预算|花费|总价|控制在|不超过)[^\d]{0,8}(\d{2,7})\s*(?:元|块)?", instruction)
    if budget_match:
        actions.append(ReplanActionIn(type="set_budget", value=int(budget_match.group(1))))

    preferences = [word for word in ("摄影", "美食", "历史文化", "自然风景", "夜景", "购物", "亲子", "轻松慢游", "紧凑打卡") if word in instruction]
    if preferences and any(marker in instruction for marker in ("偏好", "喜欢", "想体验", "多安排", "轻松", "紧凑")):
        actions.append(ReplanActionIn(type="set_preferences", preferences=preferences))

    if any(marker in instruction for marker in ("删除", "去掉", "不要")):
        matches = [item for item in current_stops if item.name in instruction]
        if len(matches) == 1:
            actions.append(ReplanActionIn(type="remove_attraction", attraction_id=matches[0].id))
        elif len(matches) > 1:
            questions.append("你想删除哪一个景点？请写出完整景点名称。")
        else:
            names = "、".join(item.name for item in current_stops)
            questions.append(f"请说明要删除的景点。当前行程包含：{names or '暂无景点'}。")

    replacement_match = re.search(r"(?:把|将)\s*([^，。；;]+?)\s*(?:替换成|换成)\s*([^，。；;]+)", instruction)
    if replacement_match:
        source_name, target_name = (value.strip() for value in replacement_match.groups())
        source_matches = [item for item in current_stops if item.name == source_name or source_name in item.name]
        target_matches = [item for item in attractions if item.name == target_name or target_name in item.name]
        if len(source_matches) == 1 and len(target_matches) == 1:
            actions.append(ReplanActionIn(type="replace_attraction", attraction_id=source_matches[0].id, new_attraction_id=target_matches[0].id))
        else:
            questions.append("请写出要替换的原景点和新景点的完整名称，并确保新景点属于当前城市。")

    unsupported = [word for word in ("酒店", "餐厅", "机票", "火车票", "导航", "天气") if word in instruction]
    if unsupported:
        questions.append(f"当前不能直接修改{'、'.join(unsupported)}安排；请说明要调整的天数、预算或具体景点。")
    if not actions and not questions:
        questions.append("你想改哪一项？可以说明天数、预算、偏好，或写出要删除、替换的具体景点名称。")
    return actions, questions[:3]


def replan_preview(db: Session, itinerary: Itinerary, instruction: str) -> ReplanPreviewOut:
    snapshot = itinerary_dict(db, itinerary.id) or {}
    city = db.scalar(select(City).where(City.name == itinerary.city_name))
    if not city:
        raise HTTPException(409, "行程所属城市资料不存在，无法解析调整要求")
    attractions = list(db.scalars(select(Attraction).where(Attraction.city_id == city.id, Attraction.is_active.is_(True)).order_by(Attraction.id)))
    attraction_by_id = {item.id: item for item in attractions}
    model_result = generate_replan_interpretation(
        instruction,
        {"days": snapshot.get("days"), "budget_total": snapshot.get("budget_total"), "preferences": snapshot.get("preferences"), "stops": [stop for day in snapshot.get("itinerary_days", []) for stop in day.get("stops", [])]},
        [{"id": item.id, "name": item.name, "tags": item.tags} for item in attractions],
    )
    parser = "llm" if model_result else "local"
    if model_result:
        try:
            status_value = model_result.get("status")
            actions = [ReplanActionIn.model_validate(item) for item in model_result.get("actions", [])]
            questions = [str(item).strip()[:180] for item in model_result.get("questions", []) if str(item).strip()][:3]
            if status_value == "ready" and actions:
                apply_structured_replan_actions(db, itinerary, copy.deepcopy(snapshot), actions)
                return ReplanPreviewOut(status="ready", summary=replan_action_summary(actions, attraction_by_id), actions=actions, parser=parser)
            if questions:
                return ReplanPreviewOut(status="needs_clarification", summary="需要补充信息后才能安全调整行程", questions=questions, parser=parser)
        except (HTTPException, TypeError, ValueError):
            parser = "local"

    actions, questions = local_replan_preview(instruction, snapshot, attractions)
    if questions:
        return ReplanPreviewOut(status="needs_clarification", summary="需要补充信息后才能安全调整行程", questions=questions, parser=parser)
    apply_structured_replan_actions(db, itinerary, copy.deepcopy(snapshot), actions)
    return ReplanPreviewOut(status="ready", summary=replan_action_summary(actions, attraction_by_id), actions=actions, parser=parser)


@app.post("/api/v1/itineraries/{itinerary_id}/replan/preview", response_model=ReplanPreviewOut)
def preview_replan_itinerary(itinerary_id: int, data: ReplanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    itinerary = itinerary_for_user(itinerary_id, user, db)
    instruction = data.instruction.strip()
    if not instruction:
        raise HTTPException(422, "请先说明希望如何调整行程")
    return replan_preview(db, itinerary, instruction)


@app.post("/api/v1/itineraries/{itinerary_id}/replan", response_model=dict)
def replan_itinerary(itinerary_id: int, data: ReplanIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Apply only actions that the user has reviewed in the preview step."""
    ensure_csrf(request)
    itinerary = itinerary_for_user(itinerary_id, user, db)
    snapshot = itinerary_dict(db, itinerary_id) or {}
    structured_actions = list(data.actions)
    if not structured_actions:
        raise HTTPException(409, "请先预览调整结果，确认后再保存")
    apply_structured_replan_actions(db, itinerary, snapshot, structured_actions)
    current = itinerary_dict(db, itinerary_id) or {}
    save_itinerary_revision(db, itinerary.id, current, "自然语言调整前自动保存")
    itinerary.budget_total = snapshot.get("budget_total", itinerary.budget_total)
    itinerary.days = len(snapshot.get("itinerary_days", []))
    replace_itinerary_days(db, itinerary, snapshot.get("itinerary_days", []))
    itinerary.lock_version += 1
    itinerary.status = "saved"
    db.commit()
    db.expire_all()
    return itinerary_dict(db, itinerary_id)


@app.get("/api/v1/itineraries/{itinerary_id}/feedback")
def itinerary_feedback(itinerary_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    itinerary_for_user(itinerary_id, user, db)
    mine = db.scalar(select(ItineraryFeedback).where(ItineraryFeedback.itinerary_id == itinerary_id, ItineraryFeedback.user_id == user.id))
    values = list(db.scalars(select(ItineraryFeedback.rating).where(ItineraryFeedback.itinerary_id == itinerary_id)))
    return {
        "rating": mine.rating if mine else None,
        "comment": mine.comment if mine else "",
        "average": round(sum(values) / len(values), 1) if values else None,
        "count": len(values),
        "status": mine.status if mine else None,
        "admin_reply": mine.admin_reply if mine else None,
        "replied_at": mine.replied_at if mine else None,
    }


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
        feedback.status = "open"
        feedback.admin_reply = None
        feedback.replied_at = None
        feedback.handled_at = None
    db.commit()
    db.refresh(feedback)
    return feedback


@app.post("/api/v1/itineraries/{itinerary_id}/shares", response_model=ShareOut)
def create_share(itinerary_id: int, data: ShareCreateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    itinerary = itinerary_for_user(itinerary_id, user, db)
    if itinerary.status != "saved":
        raise HTTPException(409, "请先保存行程再创建分享链接")
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    share = ShareLink(itinerary_id=itinerary_id, token_hash=token_hash(raw_token), expires_at=now + timedelta(days=data.expires_days))
    db.add(share)
    db.commit()
    db.refresh(share)
    return {"id": share.id, "share_url": f"{settings.app_base_url.rstrip('/')}/share/itineraries/{raw_token}", "expires_at": share.expires_at, "created_at": share.created_at}


@app.get("/api/v1/shares", response_model=list[ShareHistoryOut])
def list_my_shares(user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = db.execute(
        select(ShareLink, Itinerary)
        .join(Itinerary, Itinerary.id == ShareLink.itinerary_id)
        .where(Itinerary.user_id == user.id)
        .order_by(ShareLink.created_at.desc(), ShareLink.id.desc())
    ).all()
    return [
        {
            "id": share.id,
            "itinerary_id": itinerary.id,
            "itinerary_title": itinerary.title,
            "city_name": itinerary.city_name,
            "status": "revoked" if share.revoked_at else "expired" if share.expires_at <= now else "active",
            "expires_at": share.expires_at,
            "revoked_at": share.revoked_at,
            "created_at": share.created_at,
        }
        for share, itinerary in rows
    ]


@app.get("/api/v1/shares/{token}")
def read_share(token: str, db: Session = Depends(get_db)):
    share = db.scalar(select(ShareLink).where(ShareLink.token_hash == token_hash(token), ShareLink.revoked_at.is_(None)))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not share or share.expires_at <= now:
        raise HTTPException(404, "分享链接不存在或已失效")
    itinerary = db.get(Itinerary, share.itinerary_id)
    owner = db.get(User, itinerary.user_id) if itinerary else None
    if not itinerary or itinerary.deleted_at is not None or itinerary.status != "saved" or not owner or not owner.is_active or owner.deleted_at is not None:
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
        target_model = {"city": City, "attraction": Attraction, "itinerary": Itinerary}.get(item.target_type)
        if target_model is None:
            continue
        target = db.get(target_model, item.target_id)
        target_city = db.get(City, target.city_id) if isinstance(target, Attraction) else target if isinstance(target, City) else None
        content_is_visible = (
            target.user_id == user.id and target.deleted_at is None
            if isinstance(target, Itinerary)
            else bool(target and target.is_active and target_city and target_city.is_active)
        )
        if target and content_is_visible:
            results.append({"target_type": item.target_type, "target_id": item.target_id, "name": getattr(target, "name", getattr(target, "title", "行程")), "description": getattr(target, "description", ""), "image_url": getattr(target, "image_url", ""), "city_id": getattr(target, "city_id", None)})
    return results


@app.put("/api/v1/favorites/{target_type}/{target_id}")
def add_favorite(target_type: str, target_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    target_model = City if target_type == "city" else Attraction if target_type == "attraction" else Itinerary if target_type == "itinerary" else None
    target = db.get(target_model, target_id) if target_model else None
    target_city = db.get(City, target.city_id) if isinstance(target, Attraction) else target if isinstance(target, City) else None
    content_is_visible = (
        target.user_id == user.id and target.deleted_at is None
        if isinstance(target, Itinerary)
        else bool(target and target.is_active and target_city and target_city.is_active)
    )
    if not target or not content_is_visible:
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
        target_city = db.get(City, target.city_id) if isinstance(target, Attraction) else target
        if target and target.is_active and target_city and target_city.is_active:
            results.append({"target_type": item.target_type, "target_id": item.target_id, "name": target.name, "description": target.description, "image_url": target.image_url, "viewed_at": item.viewed_at})
    return results


@app.post("/api/v1/recent-views", status_code=204)
def add_recent_view(target_type: str, target_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_csrf(request)
    target_model = City if target_type == "city" else Attraction if target_type == "attraction" else None
    target = db.get(target_model, target_id) if target_model else None
    target_city = db.get(City, target.city_id) if isinstance(target, Attraction) else target
    if not target or not target.is_active or not target_city or not target_city.is_active:
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
        "itineraries": db.scalar(select(func.count(Itinerary.id))),
        "deleted_itineraries": db.scalar(select(func.count(Itinerary.id)).where(Itinerary.deleted_at.is_not(None))),
        "feedback": db.scalar(select(func.count(ItineraryFeedback.id))),
        "email_outbox": db.scalar(select(func.count(EmailOutbox.id))),
        "failed_email_outbox": db.scalar(select(func.count(EmailOutbox.id)).where(EmailOutbox.status == "failed")),
        "media_assets": db.scalar(select(func.count(MediaAsset.id))),
        "photos": db.scalar(select(func.count(MediaAsset.id)).where(MediaAsset.purpose.like("photo-%"))),
        "community_posts": db.scalar(select(func.count(CommunityPost.id))),
        "community_reports": db.scalar(select(func.count(ContentReport.id)).where(ContentReport.status == "open")),
        "knowledge_documents": db.scalar(select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.status == "approved")),
    }


def admin_email_outbox_dict(delivery: EmailOutbox, account: User | None) -> dict:
    return {
        "id": delivery.id,
        "user_id": delivery.user_id,
        "username": account.username if account else None,
        "purpose": delivery.purpose,
        "recipient_masked": delivery.recipient_masked,
        "subject": delivery.subject,
        "status": delivery.status,
        "attempt_count": delivery.attempt_count,
        "retry_count": delivery.retry_count,
        "last_error_code": delivery.last_error_code,
        "sent_at": delivery.sent_at,
        "created_at": delivery.created_at,
        "updated_at": delivery.updated_at,
    }


@app.get("/api/v1/admin/email-outbox", response_model=AdminEmailOutboxPageOut)
def admin_email_outbox(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    status_filter: str = Query(default="all", alias="status", pattern="^(all|sent|failed|simulated)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    filters = [EmailOutbox.status == status_filter] if status_filter != "all" else []
    total = db.scalar(select(func.count(EmailOutbox.id)).where(*filters)) or 0
    deliveries = db.scalars(
        select(EmailOutbox).where(*filters).order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [admin_email_outbox_dict(delivery, db.get(User, delivery.user_id) if delivery.user_id else None) for delivery in deliveries],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/v1/admin/users", response_model=AdminUserPageOut)
def admin_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    status_filter: str = Query(default="all", alias="status", pattern="^(all|active|disabled)$"),
    search: str = Query(default="", max_length=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    filters = [User.email_verified_at.is_not(None)]
    if status_filter == "active":
        filters.append(User.is_active.is_(True))
    elif status_filter == "disabled":
        filters.append(User.is_active.is_(False))
    keyword = search.strip()
    if keyword:
        escaped_keyword = keyword.replace("%", "\\%").replace("_", "\\_")
        filters.append(or_(
            User.username.ilike(f"%{escaped_keyword}%"),
            User.email.ilike(f"%{escaped_keyword}%"),
            User.public_id.ilike(f"%{escaped_keyword}%"),
        ))
    total = db.scalar(select(func.count(User.id)).where(*filters)) or 0
    results = []
    accounts = db.scalars(
        select(User).where(*filters).order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    for account in accounts:
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
    return {"items": results, "total": total, "page": page, "page_size": page_size}


def admin_feedback_dict(feedback: ItineraryFeedback, itinerary: Itinerary, owner: User, assignee: User | None) -> dict:
    return {
        "id": feedback.id,
        "itinerary_id": itinerary.id,
        "username": owner.username,
        "email": owner.email,
        "city_name": itinerary.city_name,
        "itinerary_title": itinerary.title,
        "rating": feedback.rating,
        "comment": feedback.comment or "",
        "status": feedback.status,
        "assigned_admin_id": feedback.assigned_admin_id,
        "assigned_admin_username": assignee.username if assignee else None,
        "admin_reply": feedback.admin_reply,
        "replied_at": feedback.replied_at,
        "handled_at": feedback.handled_at,
        "created_at": feedback.created_at,
        "updated_at": feedback.updated_at,
    }


@app.get("/api/v1/admin/feedback", response_model=AdminFeedbackPageOut)
def admin_feedback(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status_filter: str = Query(default="all", alias="status", pattern="^(all|open|in_progress|resolved)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    filters = [ItineraryFeedback.status == status_filter] if status_filter != "all" else []
    feedback_query = select(ItineraryFeedback).join(Itinerary, Itinerary.id == ItineraryFeedback.itinerary_id).join(User, User.id == ItineraryFeedback.user_id).where(*filters)
    total = db.scalar(select(func.count(ItineraryFeedback.id)).join(Itinerary, Itinerary.id == ItineraryFeedback.itinerary_id).join(User, User.id == ItineraryFeedback.user_id).where(*filters)) or 0
    results = []
    for feedback in db.scalars(feedback_query.order_by(ItineraryFeedback.created_at.desc(), ItineraryFeedback.id.desc()).offset((page - 1) * page_size).limit(page_size)):
        itinerary = db.get(Itinerary, feedback.itinerary_id)
        owner = db.get(User, feedback.user_id)
        if itinerary and owner:
            results.append(admin_feedback_dict(feedback, itinerary, owner, db.get(User, feedback.assigned_admin_id) if feedback.assigned_admin_id else None))
    return {"items": results, "total": total, "page": page, "page_size": page_size}


@app.get("/api/v1/admin/feedback/assignees")
def admin_feedback_assignees(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    return [{"id": account.id, "username": account.username} for account in db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True)).order_by(User.username))]


@app.patch("/api/v1/admin/feedback/{feedback_id}", response_model=AdminFeedbackOut)
def update_admin_feedback(feedback_id: int, data: AdminFeedbackUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    feedback = db.get(ItineraryFeedback, feedback_id)
    if not feedback:
        raise HTTPException(404, "反馈不存在")
    before_status = feedback.status
    before_assignee = feedback.assigned_admin_id
    reply_changed = "admin_reply" in data.model_fields_set and data.admin_reply != feedback.admin_reply
    if "assigned_admin_id" in data.model_fields_set:
        if data.assigned_admin_id is None:
            feedback.assigned_admin_id = None
        else:
            assignee = db.get(User, data.assigned_admin_id)
            if not assignee or assignee.role != "admin" or not assignee.is_active:
                raise HTTPException(422, "只能分派给启用的管理员")
            feedback.assigned_admin_id = assignee.id
    if data.status is not None:
        feedback.status = data.status
    if feedback.status != "open" and feedback.assigned_admin_id is None:
        feedback.assigned_admin_id = user.id
    if "admin_reply" in data.model_fields_set:
        feedback.admin_reply = data.admin_reply.strip() if data.admin_reply else None
        feedback.replied_at = datetime.now(timezone.utc).replace(tzinfo=None) if feedback.admin_reply else None
    feedback.handled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_admin_audit(db, user, "update", "feedback", feedback.id, "更新反馈处理信息", {
        "from_status": before_status,
        "to_status": feedback.status,
        "assignment_changed": before_assignee != feedback.assigned_admin_id,
        "reply_changed": reply_changed,
    })
    db.commit()
    db.refresh(feedback)
    itinerary = db.get(Itinerary, feedback.itinerary_id)
    owner = db.get(User, feedback.user_id)
    return admin_feedback_dict(feedback, itinerary, owner, db.get(User, feedback.assigned_admin_id) if feedback.assigned_admin_id else None)


def admin_knowledge_dict(db: Session, document: KnowledgeDocument) -> dict:
    city = db.get(City, document.city_id)
    return {
        "id": document.id, "city_id": document.city_id, "city_name": city.name if city else "未知城市",
        "title": document.title, "source_name": document.source_name, "source_url": document.source_url,
        "license_note": document.license_note, "content": document.content, "status": document.status,
        "chunk_count": db.scalar(select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == document.id)) or 0,
        "updated_at": document.updated_at,
    }


@app.get("/api/v1/admin/knowledge-documents", response_model=list[AdminKnowledgeDocumentOut])
def admin_knowledge_documents(status: str = Query(default="all", pattern="^(all|needs_review|approved|rejected|archived)$"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    filters = [KnowledgeDocument.status == status] if status != "all" else []
    return [admin_knowledge_dict(db, document) for document in db.scalars(select(KnowledgeDocument).where(*filters).order_by(KnowledgeDocument.updated_at.desc()))]


@app.post("/api/v1/admin/knowledge-documents", response_model=AdminKnowledgeDocumentOut, status_code=201)
def create_knowledge_document(data: KnowledgeDocumentIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    if not db.get(City, data.city_id):
        raise HTTPException(422, "所属城市不存在")
    document = KnowledgeDocument(**data.model_dump(), status="needs_review")
    db.add(document)
    db.flush()
    rebuild_knowledge_chunks(db, document)
    record_admin_audit(db, user, "create", "knowledge_document", document.id, "录入待审核攻略资料", {"city_id": document.city_id, "chunk_count": len(document.content)})
    db.commit()
    return admin_knowledge_dict(db, document)


@app.patch("/api/v1/admin/knowledge-documents/{document_id}", response_model=AdminKnowledgeDocumentOut)
def update_knowledge_document(document_id: int, data: KnowledgeDocumentUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(404, "攻略资料不存在")
    if not db.get(City, data.city_id):
        raise HTTPException(422, "所属城市不存在")
    changed_content = document.content != data.content
    for field, value in data.model_dump().items():
        setattr(document, field, value)
    if changed_content:
        rebuild_knowledge_chunks(db, document)
    record_admin_audit(db, user, "update", "knowledge_document", document.id, "更新攻略资料或审核状态", {"status": document.status, "content_changed": changed_content})
    db.commit()
    return admin_knowledge_dict(db, document)


@app.get("/api/v1/guide-knowledge/search")
def guide_knowledge_search(city_id: int = Query(ge=1), query: str = Query(min_length=1, max_length=500), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(City, city_id):
        raise HTTPException(404, "城市不存在")
    return {"items": [{key: value for key, value in hit.items() if key != "score"} for hit in search_guide_knowledge(db, city_id, query, top_k=3)]}


@app.get("/api/v1/admin/community/posts")
def admin_community_posts(
    status_filter: str = Query(default="all", alias="status", pattern="^(all|published|hidden)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    filters = [] if status_filter == "all" else [CommunityPost.status == status_filter]
    total = db.scalar(select(func.count(CommunityPost.id)).where(*filters)) or 0
    posts = db.scalars(select(CommunityPost).where(*filters).order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [community_post_dict(db, post, user) for post in posts], "total": total, "page": page, "page_size": page_size}


@app.patch("/api/v1/admin/community/posts/{post_id}")
def admin_update_community_post(post_id: int, data: CommunityStatusUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    post = db.get(CommunityPost, post_id)
    if not post:
        raise HTTPException(404, "社区帖子不存在")
    post.status = data.status
    record_admin_audit(db, user, f"community_post_{data.status}", "community_post", post.id, f"{'公开' if data.status == 'published' else '下架'}社区帖子：{post.title}")
    db.commit()
    db.refresh(post)
    return community_post_dict(db, post, user)


@app.patch("/api/v1/admin/community/comments/{comment_id}")
def admin_update_community_comment(comment_id: int, data: CommunityStatusUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    comment = db.get(CommunityComment, comment_id)
    if not comment:
        raise HTTPException(404, "社区评论不存在")
    comment.status = data.status
    record_admin_audit(db, user, f"community_comment_{data.status}", "community_comment", comment.id, f"{'公开' if data.status == 'published' else '隐藏'}社区评论")
    db.commit()
    return {"id": comment.id, "status": comment.status}


@app.patch("/api/v1/admin/community/images/{image_id}")
def admin_update_community_image(image_id: int, data: CommunityStatusUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    image = db.get(CommunityPostImage, image_id)
    if not image:
        raise HTTPException(404, "社区图片不存在")
    image.status = data.status
    record_admin_audit(db, user, f"community_image_{data.status}", "community_image", image.id, f"{'公开' if data.status == 'published' else '隐藏'}社区图片")
    db.commit()
    return {"id": image.id, "status": image.status}


@app.get("/api/v1/admin/community/reports")
def admin_community_reports(
    status_filter: str = Query(default="open", alias="status", pattern="^(open|resolved|dismissed|all)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    filters = [] if status_filter == "all" else [ContentReport.status == status_filter]
    reports = db.scalars(select(ContentReport).where(*filters).order_by(ContentReport.created_at.desc(), ContentReport.id.desc()).limit(100))
    return [{
        "id": report.id,
        "target_type": report.target_type,
        "target_id": report.target_id,
        "reason": report.reason,
        "status": report.status,
        "created_at": report.created_at,
        "reporter": community_author_name(db, report.reporter_id),
    } for report in reports]


@app.patch("/api/v1/admin/community/reports/{report_id}")
def admin_update_community_report(report_id: int, data: ContentReportStatusUpdateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    report = db.get(ContentReport, report_id)
    if not report:
        raise HTTPException(404, "举报记录不存在")
    report.status = data.status
    record_admin_audit(db, user, f"community_report_{data.status}", "content_report", report.id, f"更新社区举报状态为：{data.status}")
    db.commit()
    return {"id": report.id, "status": report.status}


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
    action = "activate" if data.is_active else "deactivate"
    record_admin_audit(db, user, action, "user", account.id, f"{'启用' if data.is_active else '停用'}用户：{account.username}")
    db.commit()
    session_count = db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == account.id)) or 0
    deleted_count = db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == account.id, ChatSession.deleted_at.is_not(None))) or 0
    return {
        "id": account.id, "public_id": account.public_id, "username": account.username, "email": account.email, "role": account.role,
        "is_active": account.is_active, "created_at": account.created_at,
        "session_count": session_count, "deleted_session_count": deleted_count,
    }


def itinerary_association_counts(db: Session, itinerary: Itinerary) -> dict[str, int]:
    return {
        "分享": db.scalar(select(func.count(ShareLink.id)).where(ShareLink.itinerary_id == itinerary.id)) or 0,
        "反馈": db.scalar(select(func.count(ItineraryFeedback.id)).where(ItineraryFeedback.itinerary_id == itinerary.id)) or 0,
        "历史版本": db.scalar(select(func.count(ItineraryRevision.id)).where(ItineraryRevision.itinerary_id == itinerary.id)) or 0,
        "Agent 运行": db.scalar(select(func.count(AgentRun.id)).where(AgentRun.itinerary_id == itinerary.id)) or 0,
        "规划任务": db.scalar(select(func.count(PlanningJob.id)).where(PlanningJob.result_itinerary_id == itinerary.id)) or 0,
        "收藏": db.scalar(select(func.count(Favorite.id)).where(Favorite.target_type == "itinerary", Favorite.target_id == itinerary.id)) or 0,
        "社区帖子": db.scalar(select(func.count(CommunityPost.id)).where(CommunityPost.itinerary_id == itinerary.id)) or 0,
    }


def admin_itinerary_dict(db: Session, itinerary: Itinerary) -> dict:
    owner = db.get(User, itinerary.user_id) if itinerary.user_id else None
    associations = itinerary_association_counts(db, itinerary)
    association_count = sum(associations.values())
    return {
        "id": itinerary.id,
        "user_id": itinerary.user_id,
        "username": owner.username if owner else "已注销用户",
        "title": itinerary.title,
        "city_name": itinerary.city_name,
        "days": itinerary.days,
        "status": itinerary.status,
        "created_at": itinerary.created_at,
        "deleted_at": itinerary.deleted_at,
        "share_count": associations["分享"],
        "feedback_count": associations["反馈"],
        "revision_count": associations["历史版本"],
        "association_count": association_count,
        "can_hard_delete": itinerary.deleted_at is not None and association_count == 0,
    }


@app.get("/api/v1/admin/itineraries", response_model=AdminItineraryPageOut)
def admin_itineraries(
    state: str = Query(default="all", pattern="^(all|active|deleted)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=10),
    search: str = Query(default="", max_length=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    filters = []
    if state == "active":
        filters.append(Itinerary.deleted_at.is_(None))
    elif state == "deleted":
        filters.append(Itinerary.deleted_at.is_not(None))
    keyword = search.strip()
    statement = select(Itinerary)
    count_statement = select(func.count(Itinerary.id))
    if keyword:
        escaped_keyword = keyword.replace("%", "\\%").replace("_", "\\_")
        search_filter = or_(
            Itinerary.title.ilike(f"%{escaped_keyword}%"),
            Itinerary.city_name.ilike(f"%{escaped_keyword}%"),
            User.username.ilike(f"%{escaped_keyword}%"),
            User.email.ilike(f"%{escaped_keyword}%"),
        )
        statement = statement.outerjoin(User, User.id == Itinerary.user_id)
        count_statement = count_statement.outerjoin(User, User.id == Itinerary.user_id)
        filters.append(search_filter)
    total = db.scalar(count_statement.where(*filters)) or 0
    itineraries = db.scalars(
        statement.where(*filters).order_by(Itinerary.created_at.desc(), Itinerary.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {"items": [admin_itinerary_dict(db, itinerary) for itinerary in itineraries], "total": total, "page": page, "page_size": page_size}


@app.post("/api/v1/admin/itineraries/{itinerary_id}/restore", response_model=AdminItineraryOut)
def admin_restore_itinerary(itinerary_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    itinerary = db.get(Itinerary, itinerary_id)
    if not itinerary:
        raise HTTPException(404, "行程不存在")
    if itinerary.deleted_at is None:
        raise HTTPException(409, "行程未被删除")
    itinerary.deleted_at = None
    record_admin_audit(db, user, "restore", "itinerary", itinerary.id, f"恢复行程：{itinerary.title}", {"owner_user_id": itinerary.user_id})
    db.commit()
    return admin_itinerary_dict(db, itinerary)


@app.delete("/api/v1/admin/itineraries/{itinerary_id}", status_code=204)
def admin_hard_delete_itinerary(itinerary_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    itinerary = db.get(Itinerary, itinerary_id)
    if not itinerary:
        raise HTTPException(404, "行程不存在")
    if itinerary.deleted_at is None:
        raise HTTPException(409, "请先将行程移入回收站")
    associations = itinerary_association_counts(db, itinerary)
    related = [f"{name} {count} 条" for name, count in associations.items() if count]
    if related:
        raise HTTPException(409, f"行程仍有关联数据，不能彻底删除：{'、'.join(related)}")
    validation = db.scalar(select(ItineraryValidation).where(ItineraryValidation.itinerary_id == itinerary.id))
    if validation:
        db.delete(validation)
    record_admin_audit(db, user, "hard_delete", "itinerary", itinerary.id, f"彻底删除无外部关联行程：{itinerary.title}", {"owner_user_id": itinerary.user_id})
    db.delete(itinerary)
    db.commit()


@app.get("/api/v1/admin/sessions", response_model=AdminSessionPageOut)
def admin_sessions(
    state: str = Query(default="all", pattern="^(all|active|archived|deleted)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=10),
    search: str = Query(default="", max_length=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    filters = []
    if state == "active":
        filters.extend([ChatSession.deleted_at.is_(None), ChatSession.archived_at.is_(None)])
    elif state == "archived":
        filters.extend([ChatSession.deleted_at.is_(None), ChatSession.archived_at.is_not(None)])
    elif state == "deleted":
        filters.append(ChatSession.deleted_at.is_not(None))
    keyword = search.strip()
    statement = select(ChatSession)
    count_statement = select(func.count(ChatSession.id))
    if keyword:
        escaped_keyword = keyword.replace("%", "\\%").replace("_", "\\_")
        search_filter = or_(
            ChatSession.title.ilike(f"%{escaped_keyword}%"),
            User.username.ilike(f"%{escaped_keyword}%"),
            User.email.ilike(f"%{escaped_keyword}%"),
        )
        statement = statement.outerjoin(User, User.id == ChatSession.user_id)
        count_statement = count_statement.outerjoin(User, User.id == ChatSession.user_id)
        filters.append(search_filter)
    total = db.scalar(count_statement.where(*filters)) or 0
    statement = statement.where(*filters).order_by(func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc(), ChatSession.id.desc()).offset((page - 1) * page_size).limit(page_size)
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
    return {"items": results, "total": total, "page": page, "page_size": page_size}


@app.post("/api/v1/admin/sessions/{session_id}/restore", response_model=AdminSessionOut)
def admin_restore_session(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    ensure_csrf(request)
    chat = db.get(ChatSession, session_id)
    if not chat:
        raise HTTPException(404, "会话不存在")
    chat.deleted_at = None
    chat.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_admin_audit(db, user, "restore", "session", chat.id, f"恢复会话：{chat.title}", {"owner_user_id": chat.user_id})
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
