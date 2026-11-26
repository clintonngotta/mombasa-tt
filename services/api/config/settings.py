"""Django settings for the Coast TT API. All environment-specific values come from env vars
(see .env.example and deployment.md "Configuration")."""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is off.")
    SECRET_KEY = "insecure-local-development-key"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
# The browser origins allowed to use the API besides its own (core/security.py): CSRF, state-changing
# requests and WebSockets all check against this list. Production takes exact https origins only.
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173" if DEBUG else "")
if not DEBUG:
    if any("*" in host or host.startswith(".") for host in ALLOWED_HOSTS):
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS takes exact domains in production, no wildcard.")
    for origin in CSRF_TRUSTED_ORIGINS:
        if not origin.startswith("https://") or "*" in origin:
            raise ImproperlyConfigured(
                f"DJANGO_CSRF_TRUSTED_ORIGINS takes exact https:// origins in production, not {origin!r}."
            )

# Where emailed links (verification, password reset) point.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")

INSTALLED_APPS = [
    "daphne",  # runserver serves ASGI, WebSockets included
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "channels",
    "core",
    "accounts",
    "activities",
    "attachments",
    "backoffice",
    "competitions",
    "facilities",
    "feedback",
    "finance",
    "coaching",
    "events",
    "matchlog",
    "notifications",
    "profiles",
    "organizations",
    "guests",
    "outbox",
    "penalties",
    "ratings",
    "realtime",
    "regions",
    "reservations",
    "scoring",
    "soda",
    "squads",
    "training",
]

MIDDLEWARE = [
    "core.middleware.RequestIdMiddleware",
    "core.middleware.ClientBuildMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.security.OriginCheckMiddleware",
    "core.security.AdminLoginThrottleMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.IdempotencyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
CSRF_FAILURE_VIEW = "core.views.csrf_failure"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": dj_database_url.config(env="DATABASE_URL", conn_max_age=60, conn_health_checks=True)}
if not DATABASES["default"]:
    raise ImproperlyConfigured("DATABASE_URL is required (PostgreSQL).")

AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    # Keep in sync with MIN_PASSWORD_LENGTH in apps/web/src/lib/auth.ts.
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_RESET_TIMEOUT = 60 * 60
EMAIL_VERIFICATION_MAX_AGE = 24 * 60 * 60

# Session cookies are HttpOnly; the CSRF cookie stays readable so the PWA can echo it (REQ-003).
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Off until every host is checked over HTTPS (deployment.md); then set it, e.g. 31536000.
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0") or 0)
# Nothing the API serves may be framed or open a window that keeps a handle on it.
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Private attachments (REQ-020). Never served directly: content leaves only through signed links that
# last ATTACHMENT_URL_TTL seconds. Swap the "attachments" backend for S3-compatible storage in
# production (deployment.md); the API streams from whichever backend is configured.
ATTACHMENTS_ROOT = Path(os.environ.get("ATTACHMENTS_ROOT", BASE_DIR / "var" / "attachments"))
ATTACHMENT_URL_TTL = int(os.environ.get("ATTACHMENT_URL_TTL", "300"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "attachments": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": ATTACHMENTS_ROOT},
    },
}

if os.environ.get("SMTP_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["SMTP_HOST"]
    EMAIL_PORT = int(os.environ.get("SMTP_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("SMTP_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("SMTP_USE_TLS", True)
else:
    # Local development prints emails (verification/reset links) to the runserver console.
    EMAIL_BACKEND = "core.email.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Coast TT <no-reply@localhost>")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    # Applies only to views that set `throttle_scope` (anonymous auth endpoints, sending invitations).
    # ...and, for signed-out callers, the public competition pages (core/throttling.py).
    "DEFAULT_THROTTLE_CLASSES": [
        "core.throttling.ScopedThrottle",
        "core.throttling.PublicReadThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth_login": os.environ.get("THROTTLE_AUTH_LOGIN", "10/min"),
        "auth_email": os.environ.get("THROTTLE_AUTH_EMAIL", "5/min"),
        "invitations": os.environ.get("THROTTLE_INVITATIONS", "30/hour"),
        "uploads": os.environ.get("THROTTLE_UPLOADS", "30/hour"),
        "entries": os.environ.get("THROTTLE_ENTRIES", "30/hour"),
        "public_reads": os.environ.get("THROTTLE_PUBLIC_READS", "120/min"),
        "live_reads": os.environ.get("THROTTLE_LIVE_READS", "1800/min"),
        "nearby": os.environ.get("THROTTLE_NEARBY", "30/min"),
    },
    # The client address is the last X-Forwarded-For hop added by the one proxy in front (Caddy), so a
    # client can't dodge a throttle by sending its own X-Forwarded-For. With no header, REMOTE_ADDR.
    "NUM_PROXIES": int(os.environ.get("TRUSTED_PROXY_COUNT", "1")),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Coast TT API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # The live schema maps every route: signed-in callers only (the web app builds from openapi.yaml).
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    "COMPONENT_SPLIT_REQUEST": True,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "core.schema.contract_hook",
    ],
    # Several models have a `status` field; give each choice set a stable component name.
    "ENUM_NAME_OVERRIDES": {
        # Campaigns and welfare projects share one audience choice set (all or selected members).
        "FinanceAudienceEnum": "finance.models.Campaign.Audience",
        "MembershipStatusEnum": "organizations.models.Membership.Status",
        "MeetingAttendanceEnum": "regions.models.MeetingInvitee.Attendance",
        "AttendanceMarkEnum": "regions.serializers.MARKS",
        "PenalizedAttendanceEnum": "regions.serializers.PENALIZED",
        "MeetingPenaltyStatusEnum": "regions.models.MeetingPenalty.Status",
        "ActionItemStatusEnum": "regions.models.ActionItem.Status",
        "FeedbackFormStatusEnum": "feedback.models.FeedbackForm.Status",
        "SquadPlaceStatusEnum": "squads.models.SquadPlace.Status",
        "AbsenceEnum": "penalties.models.Absence",
        "ExpenseCategoryEnum": "finance.models.Expense.Category",
        "PenaltyKindEnum": "penalties.models.PenaltyKind",
        "AbsencePenaltyStatusEnum": "penalties.models.AbsencePenalty.Status",
        "AppealEnum": "penalties.models.AbsencePenalty.Appeal",
        "QuestionKindEnum": "feedback.serializers.KIND_CHOICES",
        "MinutesStatusEnum": "regions.models.Meeting.MinutesStatus",
        "SkillEnum": "training.models.Skill",
        "TableBlockReasonEnum": "reservations.models.TableBlock.Reason",
        "IncidentKindEnum": "scoring.models.MatchIncident.Kind",
        "AnnouncementScopeEnum": "competitions.models.Announcement.Scope",
        "AnnouncementStatusEnum": "competitions.models.Announcement.Status",
        "SideEnum": "reservations.control.SIDES",
        "ClubSessionStatusEnum": "training.models.ClubSession.Status",
        "RsvpAnswerEnum": "activities.models.Rsvp.Answer",
        "PaymentMethodEnum": "finance.models.Payment.Method",
        "VisitMethodEnum": "facilities.models.Visit.Method",
        "NotificationCategoryEnum": "notifications.models.Category",
        "SodaChallengeStatusEnum": "soda.models.Challenge.Status",
        "ScheduleKindEnum": "activities.serializers.SCHEDULE_KINDS",
        "ActivityStatusEnum": "activities.models.Activity.Status",
        # A welfare due's and an activity share's standing for the member who owes it.
        "OwedStatusEnum": "finance.ledger.OWED_STATUSES",
        "SessionInvitationStatusEnum": "training.models.SessionInvitation.Status",
        "CoachLevelEnum": "coaching.models.Level",
        "JoinRequestStatusEnum": "organizations.models.JoinRequest.Status",
        "MatchResultEnum": "matchlog.models.MatchResult",
        "InvitationStatusEnum": "organizations.models.Invitation.Status",
        "GuestClaimStatusEnum": "guests.models.GuestClaim.Status",
        "GuestClaimActionEnum": "guests.models.GuestClaimEvent.Action",
        "PermissionEnum": "organizations.permissions.Permission",
        "RoleKeyEnum": "organizations.permissions.RoleKey",
        "KindEnum": "organizations.models.Organization.Kind",
        "MemberFieldKindEnum": "organizations.models.MemberField.Kind",
        "MemberFieldVisibilityEnum": "organizations.models.MemberField.Visibility",
        "TournamentStatusEnum": "competitions.models.Tournament.Status",
        "TournamentScopeEnum": "competitions.models.Tournament.Scope",
        "EventStatusEnum": "competitions.models.Event.Status",
        "EventKindEnum": "competitions.models.Event.Kind",
        "SinglesOrDoublesEnum": "competitions.models.Rubber.Kind",
        "ScoringStatusEnum": "scoring.models.ScoringStatus",
        "EnginePhaseEnum": "scoring.models.EnginePhase",
        "EntryStatusEnum": "competitions.models.Entry.Status",
        "DrawStatusEnum": "competitions.models.DrawVersion.Status",
        "MatchStatusEnum": "competitions.models.Match.Status",
        "MatchStageEnum": "competitions.models.Match.Stage",
        "MatchOutcomeEnum": "competitions.models.Match.Outcome",
        "ScheduleVersionKindEnum": "competitions.models.ScheduleVersion.Kind",
        "DelayReasonEnum": "competitions.models.ScheduleVersion.Reason",
        "StreamPlatformEnum": "competitions.models.LiveStream.Platform",
        "StreamReportReasonEnum": "competitions.models.LiveStreamReport.Reason",
    },
}

# One JSON object per line (core/logging.py) with the request ID, for the log collector; plain text by
# default while developing. LOG_FORMAT=json or text overrides either.
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text" if DEBUG else "json")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "core.logging.RequestIdFilter"}},
    "formatters": {
        "json": {"()": "core.logging.JsonFormatter"},
        "text": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_id"],
            "formatter": "json" if LOG_FORMAT == "json" else "text",
        }
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# Redis carries Celery's wake-ups and the WebSocket messages between processes. It is optional while
# developing: without it the outbox is polled by `manage.py work_outbox` and WebSocket messages reach
# only pages served by the same process. Keep it on a private network (deployment.md).
REDIS_URL = os.environ.get("REDIS_URL", "")
# Production counts rate limits in Redis so every API process shares them (core/throttling.py); without
# it each process would keep its own count and a client could spread requests across them.
if not DEBUG and not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL is required when DJANGO_DEBUG is off (shared rate limits).")

# "default" holds the rate-limit counts and the second-old live score list (scoring/live.py). Calls to
# Redis give up after half a second, so a slow Redis can't hold a request. "local" is this process's own
# memory: the counts fall back to it while Redis is down, for the limits that stay open (throttling.py).
_LOCAL_CACHE = {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    "LOCATION": "coast-tt-local",
    "OPTIONS": {"MAX_ENTRIES": 10000},
}
CACHES = {
    "default": (
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "coast-tt",
            # JSON, not pickle (core/cache.py). No retries: one failed call is the answer.
            "OPTIONS": {
                "serializer": "core.cache.JsonSerializer",
                "socket_connect_timeout": 0.5,
                "socket_timeout": 0.5,
                "retry_on_timeout": False,
            },
        }
        if REDIS_URL
        else {**_LOCAL_CACHE, "LOCATION": "coast-tt-default"}
    ),
    "local": _LOCAL_CACHE,
}

# The oldest web app build (its APP_BUILD number, e.g. 202611191200) the API still serves (REQ-035).
# Raise it only when a change breaks older cached apps; 0 serves every build.
MIN_CLIENT_BUILD = int(os.environ.get("MIN_CLIENT_BUILD", "0") or 0)
# Soda game stakes (REQ-040) stay off until the legal and policy sign-off is recorded (TASK-078).
# Browser push (REQ-019, TASK-034). Off until a VAPID private key is set: make one with
# `manage.py push_keys`. The subject is how push services reach the operator (mailto: or https URL).
WEB_PUSH_PRIVATE_KEY = os.environ.get("WEB_PUSH_PRIVATE_KEY", "").strip()
WEB_PUSH_SUBJECT = os.environ.get("WEB_PUSH_SUBJECT", "") or FRONTEND_URL
# The only hosts the server sends push messages to: the browsers' own push services. Anything else a
# client sends as an endpoint is refused, so the server can't be made to post to other addresses.
WEB_PUSH_HOSTS = env_list(
    "WEB_PUSH_HOSTS",
    "fcm.googleapis.com,updates.push.services.mozilla.com,push.services.mozilla.com,"
    "web.push.apple.com,*.push.apple.com,*.notify.windows.com",
)

SODA_STAKES_ENABLED = os.environ.get("SODA_STAKES_ENABLED", "").lower() in ("1", "true", "yes")

CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_TASK_IGNORE_RESULT = True
# A task is acknowledged when it finishes, so one a dying worker held goes to another worker. The work
# itself is in the outbox table, which makes a repeat harmless.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "outbox-sweep": {"task": "outbox.work", "schedule": 5.0},
    "forget-idempotency-keys": {"task": "core.forget_idempotency_keys", "schedule": 6 * 60 * 60.0},
    "drop-expired-push-devices": {
        "task": "notifications.drop_expired_push_devices",
        "schedule": 6 * 60 * 60.0,
    },
}
# How long the answer to a change sent with an Idempotency-Key is kept (core.middleware).
IDEMPOTENCY_KEEP_DAYS = 14

CHANNEL_LAYERS = {
    "default": (
        {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}
        if REDIS_URL
        else {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    )
}
