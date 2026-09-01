from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: str
    username: str
    email: str
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
    new_password: str = Field(min_length=6, max_length=128)


class EmailChangeIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    email: EmailStr


class LoginIn(BaseModel):
    account: str
    password: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


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


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class PlanRequirementPatchIn(BaseModel):
    destination_city_id: int | None = Field(default=None, ge=1)
    days: int | None = Field(default=None, ge=2, le=5)
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


class ReplanIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)


class ShareCreateIn(BaseModel):
    expires_days: int = Field(default=30, ge=1, le=365)


class ShareOut(BaseModel):
    id: int
    share_url: str
    expires_at: datetime
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
    created_at: datetime
    updated_at: datetime
