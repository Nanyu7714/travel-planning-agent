from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: str
    username: str
    email: str
    email_verified: bool
    role: str


class UserProfileOut(BaseModel):
    display_name: str | None = None
    preferences: list[str] = Field(default_factory=list)
    avoid_places: list[str] = Field(default_factory=list)


class UserProfileUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    preferences: list[str] = Field(default_factory=list, max_length=20)
    avoid_places: list[str] = Field(default_factory=list, max_length=20)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class EmailChangeIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    email: EmailStr


class LoginIn(BaseModel):
    account: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class EmailRequestIn(BaseModel):
    email: EmailStr


class EmailVerificationIn(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class AuthTokenIn(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class PasswordResetIn(AuthTokenIn):
    new_password: str = Field(min_length=10, max_length=128)


class AuthActionOut(BaseModel):
    message: str
    dev_action_url: str | None = None
    masked_email: str | None = None
    expires_in_seconds: int | None = None
    retry_after_seconds: int | None = None


class AccountDeleteIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class CityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    slug: str
    name: str
    description: str
    season: str
    budget: str
    recommended_days: str
    image_url: str
    support_level: str
    planning_enabled: bool
    is_active: bool


class AttractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    city_id: int
    name: str
    description: str
    tags: list
    opening_hours: str
    ticket_price: int
    duration_minutes: int
    area: str
    latitude: float | None
    longitude: float | None
    image_url: str
    source: str
    is_active: bool


class AdminCityCreateIn(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(min_length=1, max_length=2000)
    season: str = Field(min_length=1, max_length=120)
    budget: str = Field(min_length=1, max_length=80)
    recommended_days: str = Field(min_length=1, max_length=40)
    image_url: str = Field(default="", max_length=500)
    support_level: str = Field(default="full", max_length=20)
    planning_enabled: bool = True
    is_active: bool = True


class AdminCityUpdateIn(BaseModel):
    slug: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    aliases: list[str] | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    season: str | None = Field(default=None, min_length=1, max_length=120)
    budget: str | None = Field(default=None, min_length=1, max_length=80)
    recommended_days: str | None = Field(default=None, min_length=1, max_length=40)
    image_url: str | None = Field(default=None, max_length=500)
    support_level: str | None = Field(default=None, max_length=20)
    planning_enabled: bool | None = None
    is_active: bool | None = None


class AdminCityOut(CityOut):
    aliases: list[str]
    attraction_count: int


class AdminAttractionCreateIn(BaseModel):
    city_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=3000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    opening_hours: str = Field(default="全天开放", max_length=120)
    ticket_price: int = Field(default=0, ge=0, le=100000)
    duration_minutes: int = Field(default=120, ge=10, le=1440)
    area: str = Field(default="", max_length=80)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    image_url: str = Field(default="", max_length=500)
    source: str = Field(default="管理员维护", max_length=200)
    is_active: bool = True


class AdminAttractionUpdateIn(BaseModel):
    city_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=3000)
    tags: list[str] | None = Field(default=None, max_length=20)
    opening_hours: str | None = Field(default=None, max_length=120)
    ticket_price: int | None = Field(default=None, ge=0, le=100000)
    duration_minutes: int | None = Field(default=None, ge=10, le=1440)
    area: str | None = Field(default=None, max_length=80)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    image_url: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class AdminAttractionOut(AttractionOut):
    city_name: str


class AdminCityImportIn(BaseModel):
    items: list[AdminCityCreateIn] = Field(min_length=1, max_length=100)


class AdminAttractionImportIn(BaseModel):
    items: list[AdminAttractionCreateIn] = Field(min_length=1, max_length=200)


class AdminRankingCreateIn(BaseModel):
    ranking_type: Literal["city", "attraction"]
    city_id: int | None = Field(default=None, ge=1)
    attraction_id: int | None = Field(default=None, ge=1)
    rank: int = Field(ge=1, le=999)
    score: int = Field(default=0, ge=0, le=100)
    reason: str = Field(default="管理员维护", min_length=1, max_length=255)
    is_active: bool = True


class AdminRankingUpdateIn(BaseModel):
    rank: int | None = Field(default=None, ge=1, le=999)
    score: int | None = Field(default=None, ge=0, le=100)
    reason: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class AdminRankingImportIn(BaseModel):
    items: list[AdminRankingCreateIn] = Field(min_length=1, max_length=200)


class AdminRankingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ranking_type: str
    city_id: int | None
    attraction_id: int | None
    target_name: str
    rank: int
    score: int
    reason: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminAuditLogOut(BaseModel):
    id: int
    actor_username: str
    action: str
    target_type: str
    target_id: int | None
    summary: str
    created_at: datetime


class AdminAuditLogPageOut(BaseModel):
    items: list[AdminAuditLogOut]
    total: int
    page: int
    page_size: int


class AdminEmailOutboxOut(BaseModel):
    id: int
    user_id: int | None
    username: str | None
    purpose: str
    recipient_masked: str
    subject: str
    status: str
    attempt_count: int
    retry_count: int
    last_error_code: str | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminEmailOutboxPageOut(BaseModel):
    items: list[AdminEmailOutboxOut]
    total: int
    page: int
    page_size: int


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    city_id: int
    attraction_id: int | None
    purpose: str
    content_key: str
    storage_type: str
    url: str | None
    storage_path: str | None
    mime_type: str | None
    alt_text: str
    source_name: str | None
    source_author: str | None
    license_name: str | None
    attribution_url: str | None
    verification_status: str
    is_active: bool


class MediaAssetUpdateIn(BaseModel):
    storage_type: Literal["remote_url", "local_file", "object_storage"] | None = None
    url: str | None = Field(default=None, max_length=1000)
    storage_path: str | None = Field(default=None, max_length=500)
    mime_type: str | None = Field(default=None, max_length=80)
    alt_text: str | None = Field(default=None, min_length=1, max_length=240)
    source_name: str | None = Field(default=None, max_length=120)
    source_author: str | None = Field(default=None, max_length=200)
    license_name: str | None = Field(default=None, max_length=120)
    attribution_url: str | None = Field(default=None, max_length=1000)
    verification_status: Literal["approved", "needs_review", "missing", "rejected_wrong_city"] | None = None
    is_active: bool | None = None


class MediaAssetBulkUpdateIn(BaseModel):
    asset_ids: list[int] = Field(min_length=1, max_length=100)
    verification_status: Literal["approved", "needs_review", "missing", "rejected_wrong_city"] | None = None
    is_active: bool | None = None


class AdminPhotoFetchIn(BaseModel):
    city_id: int = Field(ge=1)
    attraction_id: int | None = Field(default=None, ge=1)
    keyword: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=3, ge=1, le=10)
    auto_approve: bool = False


class AdminPhotoFetchOut(BaseModel):
    keyword: str
    fetched: int
    skipped: int
    providers: list[str]
    items: list[MediaAssetOut]


class PageOut(BaseModel):
    items: list
    total: int
    page: int = 1
    page_size: int = 20


class SessionOut(BaseModel):
    id: int
    title: str
    is_pinned: bool
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class SessionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    is_pinned: bool | None = None
    archived: bool | None = None


class SessionBulkUpdateIn(BaseModel):
    session_ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["archive", "restore", "delete"]
    password: str | None = Field(default=None, max_length=128)


class AdminUserOut(BaseModel):
    id: int
    public_id: str | None
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    session_count: int
    deleted_session_count: int


class AdminUserPageOut(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    page_size: int


class AdminUserUpdateIn(BaseModel):
    is_active: bool


class AdminSessionOut(BaseModel):
    id: int
    user_id: int | None
    username: str
    email: str
    title: str
    state: str
    message_count: int
    job_count: int
    created_at: datetime
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


class AdminSessionPageOut(BaseModel):
    items: list[AdminSessionOut]
    total: int
    page: int
    page_size: int


class AdminItineraryOut(BaseModel):
    id: int
    user_id: int | None
    username: str
    title: str
    city_name: str
    days: int
    status: str
    created_at: datetime
    deleted_at: datetime | None = None
    share_count: int
    feedback_count: int
    revision_count: int
    association_count: int
    can_hard_delete: bool


class AdminItineraryPageOut(BaseModel):
    items: list[AdminItineraryOut]
    total: int
    page: int
    page_size: int


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class PlanRequirementPatchIn(BaseModel):
    origin_city_id: int | None = Field(default=None, ge=1)
    destination_city_id: int | None = Field(default=None, ge=1)
    days: int | None = Field(default=None, ge=2, le=5)
    attraction_count: int | None = Field(default=None, ge=1, le=12)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    budget_total: int | None = Field(default=None, ge=0, le=10_000_000)
    interests: list[str] | None = Field(default=None, max_length=20)
    avoid_places: list[str] | None = Field(default=None, max_length=20)
    pace: Literal["relaxed", "balanced", "packed"] | None = None
    traveler_count: int | None = Field(default=None, ge=1, le=20)
    transport: Literal["public_transport", "taxi", "walking", "driving"] | None = None


class PlanConfirmIn(BaseModel):
    confirmed: bool
    patch: PlanRequirementPatchIn = Field(default_factory=PlanRequirementPatchIn)


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    payload: dict | None = None
    created_at: datetime


class ItineraryOut(BaseModel):
    id: int
    title: str
    city_name: str
    days: int
    status: str
    budget_total: int
    budget_scope: str
    preferences: list[str] = Field(default_factory=list)
    lock_version: int
    itinerary_days: list


class ItineraryStopEditIn(BaseModel):
    attraction_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    start_time: str = Field(min_length=4, max_length=10)
    end_time: str = Field(min_length=4, max_length=10)
    note: str = Field(default="", max_length=255)


class ItineraryDayEditIn(BaseModel):
    day_number: int = Field(ge=1, le=10)
    title: str = Field(min_length=1, max_length=120)
    stops: list[ItineraryStopEditIn] = Field(default_factory=list, max_length=10)


class ItineraryUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    days: int | None = Field(default=None, ge=1, le=10)
    budget_total: int | None = Field(default=None, ge=0, le=10_000_000)
    preferences: list[str] | None = Field(default=None, max_length=20)
    expected_version: int | None = Field(default=None, ge=1)
    itinerary_days: list[ItineraryDayEditIn] | None = Field(default=None, max_length=10)


class ItineraryRevisionOut(BaseModel):
    id: int
    version_no: int
    reason: str
    created_at: datetime


class ReplanActionIn(BaseModel):
    type: Literal["set_budget", "set_days", "set_preferences", "remove_attraction", "replace_attraction"]
    value: int | None = Field(default=None, ge=0, le=100000)
    attraction_id: int | None = Field(default=None, ge=1)
    new_attraction_id: int | None = Field(default=None, ge=1)
    preferences: list[str] | None = Field(default=None, max_length=20)


class ReplanIn(BaseModel):
    instruction: str = Field(default="", max_length=1000)
    actions: list[ReplanActionIn] = Field(default_factory=list, max_length=20)


class ReplanPreviewOut(BaseModel):
    status: Literal["ready", "needs_clarification"]
    summary: str
    actions: list[ReplanActionIn] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    parser: Literal["llm", "local"]


class ShareCreateIn(BaseModel):
    expires_days: int = Field(default=30, ge=1, le=365)


class ShareOut(BaseModel):
    id: int
    share_url: str
    expires_at: datetime
    created_at: datetime


class ShareHistoryOut(BaseModel):
    id: int
    itinerary_id: int
    itinerary_title: str
    city_name: str
    status: Literal["active", "expired", "revoked"]
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=10)
    comment: str = Field(default="", max_length=2000)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating: int
    comment: str
    created_at: datetime
    updated_at: datetime


class FeedbackSummaryOut(BaseModel):
    rating: int | None
    comment: str
    average: float | None
    count: int
    status: Literal["open", "in_progress", "resolved"] | None
    admin_reply: str | None
    replied_at: datetime | None


class CommunityPostCreateIn(BaseModel):
    itinerary_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=5000)


class CommunityPostUpdateIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=5000)


class CommunityCommentCreateIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


class ContentReportCreateIn(BaseModel):
    target_type: Literal["post", "comment", "image"]
    target_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class CommunityStatusUpdateIn(BaseModel):
    status: Literal["published", "hidden"]


class ContentReportStatusUpdateIn(BaseModel):
    status: Literal["open", "resolved", "dismissed"]


class AuthSessionOut(BaseModel):
    id: int
    device_name: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    current: bool = False


class AdminFeedbackOut(BaseModel):
    id: int
    itinerary_id: int
    username: str
    email: str
    city_name: str
    itinerary_title: str
    rating: int
    comment: str
    status: Literal["open", "in_progress", "resolved"]
    assigned_admin_id: int | None
    assigned_admin_username: str | None
    admin_reply: str | None
    replied_at: datetime | None
    handled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminFeedbackPageOut(BaseModel):
    items: list[AdminFeedbackOut]
    total: int
    page: int
    page_size: int


class AdminFeedbackUpdateIn(BaseModel):
    status: Literal["open", "in_progress", "resolved"] | None = None
    assigned_admin_id: int | None = Field(default=None, ge=1)
    admin_reply: str | None = Field(default=None, max_length=2000)


class AdminFeedbackAssigneeOut(BaseModel):
    id: int
    username: str


class KnowledgeDocumentIn(BaseModel):
    city_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    source_name: str = Field(min_length=1, max_length=160)
    source_url: str | None = Field(default=None, max_length=1000)
    license_note: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=80, max_length=30000)


class KnowledgeDocumentUpdateIn(KnowledgeDocumentIn):
    status: Literal["needs_review", "approved", "rejected", "archived"]


class AdminKnowledgeDocumentOut(BaseModel):
    id: int
    city_id: int
    city_name: str
    title: str
    source_name: str
    source_url: str | None
    license_note: str | None
    content: str
    status: str
    chunk_count: int
    updated_at: datetime
