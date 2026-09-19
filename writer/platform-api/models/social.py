"""Pydantic request/response schemas for the Social Media module (publish path)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SocialAccountResponse(BaseModel):
    account_id: str
    platform: str
    handle: Optional[str] = None
    reconnect_required: bool = False


class SocialProfileResponse(BaseModel):
    """The client's PostPeer profile (Social group) id — created on demand."""
    profile_id: str


class SocialSetCredentialRequest(BaseModel):
    """Set the client's PostForMe project API key (validated live before storing)."""
    api_key: str = Field(min_length=1)


class SocialCredentialStatusResponse(BaseModel):
    """Non-secret connection status for the UI — the key itself is never returned."""
    configured: bool
    provider: str


class SocialConnectUrlResponse(BaseModel):
    """A per-client OAuth connect URL for one platform (open in a new tab)."""
    platform: str
    url: str


class SocialPostCreateRequest(BaseModel):
    platform: str
    account_id: str
    copy: str = ""
    image_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    platform_specific: Optional[dict] = None
    format: str = "feed"
    title: Optional[str] = None   # YouTube video title (required for YouTube; ignored elsewhere)
    board_id: Optional[str] = None   # Pinterest board id (required for Pinterest; ignored elsewhere)
    scheduled_at: Optional[datetime] = None   # future time to publish; omit = now


class SocialDraftCopyRequest(BaseModel):
    """Ask the AI to draft post copy for one platform from a source + angle."""
    platform: str
    source_type: str = "topic"           # topic | url | blog_run | local_seo_page
    source_id: Optional[str] = None      # run_id (blog_run) or page_id (local_seo_page)
    url: Optional[str] = None            # source_type=url
    text: Optional[str] = None           # source_type=topic — freeform topic/notes
    angle: Optional[str] = None          # optional hook/angle hint
    tone: Optional[str] = None           # optional tone hint
    format: str = "feed"
    include_hashtags: bool = True


class SocialDraftCopyResponse(BaseModel):
    copy: str
    platform: str
    char_count: int
    char_limit: Optional[int] = None
    over_limit: bool = False
    source_title: Optional[str] = None
    source_version: Optional[str] = None
    angle: Optional[str] = None
    voice_warnings: list[str] = Field(default_factory=list)
    spec_warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SocialAnglesRequest(BaseModel):
    """Propose distinct editorial angles for a Source."""
    source_type: str = "topic"           # topic | url | blog_run | local_seo_page
    source_id: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None


class SocialAngle(BaseModel):
    title: str
    hook: str = ""
    description: str = ""


class SocialFanoutRequest(BaseModel):
    """Fan ONE angle out across platforms into Drafts."""
    source_type: str = "topic"
    source_id: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None
    angle: str                            # the hook/idea that drives the copy
    angle_title: Optional[str] = None     # short label stored on the drafts
    tone: Optional[str] = None
    platforms: list[str] = Field(default_factory=list)
    format: str = "feed"
    include_image: bool = False
    include_hashtags: bool = True
    slides: Optional[int] = None           # carousel: number of slides (2..max); None = default


class SocialDraftResponse(BaseModel):
    id: UUID
    client_id: UUID
    angle_set_id: Optional[UUID] = None
    angle: Optional[str] = None
    platform: str
    format: str = "feed"
    copy: Optional[str] = None
    image_urls: list[str] = Field(default_factory=list)
    media: list[dict] = Field(default_factory=list)
    platform_metadata: Optional[dict] = None
    voice_verdict: Optional[dict] = None
    spec_verdict: Optional[dict] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


class SocialFanoutResponse(BaseModel):
    angle_set_id: UUID
    job_id: UUID
    drafts: list[SocialDraftResponse] = Field(default_factory=list)


class SocialDraftUpdateRequest(BaseModel):
    copy: Optional[str] = None
    image_urls: Optional[list[str]] = None
    platform_metadata: Optional[dict] = None
    board_id: Optional[str] = None   # Pinterest board id (folds into platform_metadata)


class SocialDraftPublishRequest(BaseModel):
    account_id: str
    scheduled_at: Optional[datetime] = None
    force_qa: bool = False   # 'Publish anyway' — override a CRITICAL QA block


class SocialJobStatusResponse(BaseModel):
    id: UUID
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None

    model_config = {"extra": "ignore"}


class SocialGenerateImageRequest(BaseModel):
    """Generate one on-brand social image for a platform via Nano Banana Pro."""
    platform: str
    format: str = "feed"
    description: str                       # what the image should show
    aspect_ratio: Optional[str] = None     # override the per-platform default


class SocialGenerateImageResponse(BaseModel):
    url: str
    type: str
    aspect_ratio: str
    cost_usd: float


class SocialMediaUploadResponse(BaseModel):
    url: str
    type: str


class SocialPresignRequest(BaseModel):
    content_type: str


class SocialPresignResponse(BaseModel):
    upload_url: str
    public_url: str
    type: str
    headers: dict = Field(default_factory=dict)


class SocialPostResponse(BaseModel):
    id: UUID
    client_id: UUID
    draft_id: Optional[UUID] = None
    platform: str
    account_id: Optional[str] = None
    status: str
    status_detail: Optional[str] = None
    provider_post_id: Optional[str] = None
    post_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


# ── P1 competitor research ────────────────────────────────────────────────────

class SocialCompetitorHandle(BaseModel):
    id: Optional[UUID] = None
    competitor_id: UUID
    platform: str
    handle: str

    model_config = {"extra": "ignore"}


class SocialCompetitorResponse(BaseModel):
    """A client's competitor plus its per-platform social handles (Competitors tab)."""
    id: UUID
    name: Optional[str] = None
    domain: Optional[str] = None
    handles: list[SocialCompetitorHandle] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class SocialAddHandleRequest(BaseModel):
    platform: str
    handle: str


class SocialCompetitorSignalResponse(BaseModel):
    id: UUID
    competitor_id: Optional[UUID] = None
    competitor_name: Optional[str] = None
    platform: str
    themes: Optional[list[str]] = None
    formats: Optional[dict] = None
    hook_patterns: Optional[list[str]] = None
    cadence: Optional[dict] = None
    top_performers: Optional[list[dict]] = None
    whats_working: Optional[str] = None
    status: str
    captured_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


class SocialResearchTriggerResponse(BaseModel):
    job_id: UUID
    already_running: bool = False


# ── P3 Manager: calendar / edit / approval queue / policy / schedules ─────────

class SocialRescheduleRequest(BaseModel):
    scheduled_at: datetime


class SocialEditPostRequest(BaseModel):
    copy: Optional[str] = None
    image_urls: Optional[list[str]] = None


class SocialBatchPublishItem(BaseModel):
    draft_id: UUID
    account_id: str
    scheduled_at: Optional[datetime] = None   # future time; omit = publish now


class SocialBatchPublishRequest(BaseModel):
    items: list[SocialBatchPublishItem] = Field(default_factory=list)


class SocialBatchPublishResult(BaseModel):
    draft_id: str
    ok: bool
    post_id: Optional[str] = None
    error: Optional[str] = None


class SocialPolicyResponse(BaseModel):
    monthly_ceiling_usd: Optional[float] = None
    image_prompt_template: Optional[str] = None
    text_prompt_template: Optional[str] = None
    effective_ceiling_usd: float
    default_ceiling_usd: float
    # P4 planning fields (the autonomy loop's tuning).
    autonomy_tier: int = 0
    allowed_topics: list[str] = Field(default_factory=list)
    blocked_topics: list[str] = Field(default_factory=list)
    tone_prefs: Optional[str] = None
    competitor_focus: list[str] = Field(default_factory=list)
    qa_gate: bool = False
    # Read-only context for the UI: the effective tier ceiling + whether the loop is on
    # globally (so the Settings tab can explain why a tier is/isn't live).
    autonomy_cap_tier: int = 2
    autonomy_enabled: bool = False


class SocialPolicyUpdateRequest(BaseModel):
    """PUT the Social Policy fields. Only fields present in the request are changed; an
    explicit null clears that field (ceiling→default, templates/tone→none, topic lists→empty).
    Unset fields are untouched. Consumer fields (owner Q3): ceiling + prompt templates. P4
    planning fields: autonomy_tier + topic bank + tone/competitor focus."""
    monthly_ceiling_usd: Optional[float] = None
    image_prompt_template: Optional[str] = None
    text_prompt_template: Optional[str] = None
    # P4 planning fields.
    autonomy_tier: Optional[int] = None
    allowed_topics: Optional[list[str]] = None
    blocked_topics: Optional[list[str]] = None
    tone_prefs: Optional[str] = None
    competitor_focus: Optional[list[str]] = None
    qa_gate: Optional[bool] = None


class SocialAutonomyRunResponse(BaseModel):
    """One Social Manager (autonomy) ledger row, shaped for the activity view:
    produced/queued/proposed + cost, most-recent first."""
    id: UUID
    trigger: Optional[str] = None
    tier: Optional[int] = None
    produced: int = 0
    auto_queued: bool = False
    proposed: int = 0
    storyboards: int = 0
    platforms: list[str] = Field(default_factory=list)
    cost_usd: Optional[float] = None
    at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


class SocialScheduleItem(BaseModel):
    id: Optional[UUID] = None
    platform: str
    account_id: Optional[str] = None
    cadence: str = "disabled"
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    hour_local: int = 9
    is_active: bool = False
    auto_fill: bool = False
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


class SocialSchedulesResponse(BaseModel):
    timezone: Optional[str] = None
    auto_publish_enabled: bool = False
    schedules: list[SocialScheduleItem] = Field(default_factory=list)


class SocialScheduleUpsertRequest(BaseModel):
    platform: str
    account_id: Optional[str] = None
    cadence: str = "disabled"                # disabled | weekly | biweekly | monthly
    day_of_week: Optional[int] = None        # 0=Mon (weekly/biweekly)
    day_of_month: Optional[int] = None       # 1..28 (monthly)
    hour_local: int = 9
    is_active: bool = True
    auto_fill: bool = False                  # drip queued drafts (gated + opt-in)


# ── P5 (slice a): Video Storyboard — a brief the client shoots (NO rendered video) ─

class SocialStoryboardRequest(BaseModel):
    """Generate a shot-by-shot video storyboard from a Source for a Reel / Short."""
    platform: str                            # instagram | facebook | youtube
    source_type: str = "topic"               # topic | url | blog_run | local_seo_page
    source_id: Optional[str] = None          # run_id (blog_run) or page_id (local_seo_page)
    url: Optional[str] = None                # source_type=url
    text: Optional[str] = None               # source_type=topic — freeform topic/notes
    angle: Optional[str] = None
    tone: Optional[str] = None
    format: str = "reel"                     # reel | short


class SocialStoryboardShot(BaseModel):
    n: Optional[int] = None
    visual: str
    on_screen_text: Optional[str] = None
    voiceover: Optional[str] = None
    duration_seconds: Optional[int] = None
    b_roll: Optional[bool] = None

    model_config = {"extra": "ignore"}


class SocialStoryboardBody(BaseModel):
    hook: str = ""
    duration_seconds: Optional[int] = None
    shots: list[SocialStoryboardShot] = Field(default_factory=list)
    music: Optional[str] = None
    caption: Optional[str] = None
    hashtags: list[str] = Field(default_factory=list)
    cta: Optional[str] = None

    model_config = {"extra": "ignore"}


class SocialStoryboardResponse(BaseModel):
    id: UUID
    client_id: UUID
    platform: str
    format: str = "reel"
    source_type: Optional[str] = None
    source_title: Optional[str] = None
    angle: Optional[str] = None
    tone: Optional[str] = None
    title: Optional[str] = None
    storyboard: dict = Field(default_factory=dict)
    thumbnail_url: Optional[str] = None
    doc_url: Optional[str] = None
    voice_warnings: Optional[list[str]] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}


class SocialStoryboardUpdateRequest(BaseModel):
    """Human edit of a storyboard. Only fields present are changed."""
    title: Optional[str] = None
    storyboard: Optional[SocialStoryboardBody] = None
    thumbnail_url: Optional[str] = None


class SocialStoryboardExportResponse(BaseModel):
    """Result of exporting a storyboard to a Google Doc in the client's Drive folder."""
    doc_id: Optional[str] = None
    doc_url: Optional[str] = None
    reused: bool = False
