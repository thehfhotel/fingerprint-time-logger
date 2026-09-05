"""
Unified Configuration for Fingerprint Time Logger
Simplified configuration management for the unified FastAPI system
"""

from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field
from typing import Optional


class Settings(BaseSettings):
    """
    Unified settings for the fingerprint time logger application.
    All configuration values are centralized here with clear defaults.
    """

    # ========================================================================
    # DATABASE CONFIGURATION
    # ========================================================================
    database_url: str = "sqlite:///./database/attendance.db"

    # ========================================================================
    # ZKTECO DEVICE CONFIGURATION
    # ========================================================================
    zkteco_host: str = "192.168.100.209"  # Updated to current working device
    zkteco_port: int = 4370
    zkteco_password: int = 0
    zkteco_timeout: int = 5
    zkteco_max_retries: int = 3

    # Catch-up backfill lookback window: `zk_session._reconcile_attendance`
    # scopes its watermark to `device_id` and subtracts this many hours
    # before dedup-checking a record, so a punch missed by a blind
    # live_capture window self-heals on the next sweep instead of being
    # permanently blocked by a stale/advanced watermark. `full=True`
    # bypasses this floor entirely (dedup-only, whole-log reconcile).
    # No FINGERPRINT_ prefix — aliased to the exact env var name so ops
    # can set it directly (see docs/agents / deploy payload).
    zk_catchup_lookback_hours: int = Field(
        48, validation_alias="ZK_CATCHUP_LOOKBACK_HOURS"
    )

    # Expected container UTC offset in minutes (+07:00 Bangkok = 420).
    # `zk_session.start()` checks the actual local offset against this at
    # startup and logs critical + Slack-alerts (never crashes) on mismatch,
    # since every Bangkok-naive timestamp conversion in zk_session.py
    # silently corrupts if the container TZ isn't actually Bangkok.
    zk_expected_utc_offset_minutes: int = Field(
        420, validation_alias="ZK_EXPECTED_UTC_OFFSET_MINUTES"
    )

    # ========================================================================
    # SERVER CONFIGURATION (Unified FastAPI)
    # ========================================================================
    server_host: str = "0.0.0.0"  # nosec B104 — intended: binds inside the Docker container; nginx/Cloudflare fronts the public surface
    server_port: int = 5000  # Unified server port (was dual 5000/8000)
    secret_key: str = "fingerprint-time-logger-2025"
    
    # ========================================================================
    # LOGGING CONFIGURATION
    # ========================================================================
    log_level: str = "INFO"
    
    # ========================================================================
    # SYNC & PERFORMANCE SETTINGS
    # ========================================================================
    sync_interval_seconds: int = 30
    clear_device_after_sync: bool = False
    
    # ========================================================================
    # EXPORT SETTINGS (Simplified)
    # ========================================================================
    export_max_records: int = 50000
    export_timeout_seconds: int = 300
    export_default_format: str = "csv"
    
    # ========================================================================
    # DEVELOPMENT vs PRODUCTION
    # ========================================================================
    environment: str = "development"  # development, production
    debug: bool = True
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment"""
        return self.environment.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment"""
        return self.environment.lower() == "development"

    model_config = ConfigDict(
        env_file=".env",
        env_prefix="FINGERPRINT_",  # Environment variables prefix
        case_sensitive=False
    )


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """
    Get the global settings instance.
    This function provides dependency injection for FastAPI endpoints.
    """
    return settings


def get_database_url() -> str:
    """Get the database URL for SQLAlchemy"""
    return settings.database_url


def get_device_config() -> dict:
    """Get ZKTeco device configuration as a dictionary"""
    return {
        "host": settings.zkteco_host,
        "port": settings.zkteco_port, 
        "password": settings.zkteco_password,
        "timeout": settings.zkteco_timeout,
        "max_retries": settings.zkteco_max_retries,
    }


def get_server_config() -> dict:
    """Get server configuration for uvicorn"""
    return {
        "host": settings.server_host,
        "port": settings.server_port,
        "log_level": settings.log_level.lower(),
        "reload": settings.is_development,
    }


# ============================================================================
# HF ID — OIDC IDENTITY PROVIDER (optional; ships DARK when unset)
# ============================================================================
# These are read directly via os.getenv() in app/services/oidc_service.py
# (same pattern as JWT_SECRET / LINE_* / CF_* — secrets never live in this
# pydantic Settings object or the image). Documented here for discoverability.
#
#   HFID_SIGNING_KEY   RSA private key PEM (RS256). REQUIRED to enable HF ID.
#                      When unset/blank/unparseable the entire /oidc surface
#                      returns 404 (dark, like CF_AUTO_LOGIN). Supports either
#                      real newlines or a single line with "\n" escapes.
#                      Generate: openssl genrsa 2048
#   HFID_CLIENT_ID     Confidential client id = Cloudflare Access.
#   HFID_CLIENT_SECRET Confidential client secret = Cloudflare Access.
#   HFID_ISSUER        Issuer URL. Default https://id.thehfhotel.org/oidc
#                      (every endpoint URL derives from this).
#   HFID_REDIRECT_URIS Comma-separated exact-match redirect_uri allowlist.
#                      Default is the Cloudflare Access team callback:
#                      https://laikaexpress.cloudflareaccess.com/cdn-cgi/access/callback
#
#   READER_RESOLVE_SECRET  Shared APP↔CENTRAL secret for the server-to-server
#                      card-login surface: POST /api/private/reader/{resolve,
#                      resolve-badge,claim,wait,hk-escalate}. The same secret
#                      also guards the housekeeping room-check escalation
#                      (/hk-escalate), which additionally needs
#                      STAFF_OA_CHANNEL_ACCESS_TOKEN below to actually push —
#                      without it the endpoint answers 503 and new-hotel
#                      retries. Each consuming app's BACKEND holds it to
#                      resolve a UID (/resolve), pair a terminal to a reader
#                      (/claim) and long-poll for the tap + receive a signed
#                      card assertion (/wait). Read directly via os.getenv() in
#                      app/api/reader.py and compared constant-time against the
#                      X-Reader-Secret header. When unset/blank that surface is
#                      dark (returns 404), like HF ID without a signing key.
#
#   READER_SECRET      Shared READER↔CENTRAL secret for the tap ingest POST
#                      /api/private/reader/scan — only the ESP32 reader holds
#                      it. Distinct from READER_RESOLVE_SECRET so a compromised
#                      app backend cannot forge taps. Read directly via
#                      os.getenv() in app/api/reader.py, compared constant-time
#                      against X-Reader-Secret. Unset/blank ⇒ /scan is dark
#                      (returns 404). The signed card assertion /wait returns is
#                      an RS256 OIDC id_token, so /wait ALSO needs HFID_SIGNING_KEY
#                      set to actually mint (it is, in production).
# ============================================================================


# ============================================================================
# EMPLOYEE HUB — STAFF LINE OA (optional; ships DARK when unset)
# ============================================================================
# The Employee Hub is the rich menu on the dedicated STAFF LINE Official
# Account (Messaging API channel) — a different channel from LINE_CHANNEL_*
# (the LINE Login channel behind QR check-in OAuth). Secrets are read
# directly via os.getenv() in app/services/staff_oa_service.py (same
# pattern as the HFID_* keys above). Documented here for discoverability.
#
#   STAFF_OA_CHANNEL_ACCESS_TOKEN
#                      Long-lived Messaging API channel access token of the
#                      staff OA. Used for rich-menu CRUD, per-user Role Menu
#                      linking and webhook replies.
#   STAFF_OA_CHANNEL_SECRET
#                      Channel secret of the same OA. Verifies the
#                      X-Line-Signature (HMAC-SHA256 of the raw body) on
#                      POST /api/public/staff-oa/webhook.
#
# EITHER unset/blank ⇒ the feature is DARK (fail closed): the webhook
# answers 503 and scripts/staff_oa_sync.py refuses to run. Zero behavior
# change until both are delivered to the prod host .env, like HFID_*.
#
# GUEST-FEEDBACK GROUP FORWARDER (separate, independently dark). LINE allows
# only ONE Official Account per group chat, and the staff group hosts the
# staff OA above — so the guest-feedback app cannot receive that group's
# events itself. The webhook relays them instead, fire-and-forget, and
# guest-feedback replies into the group with the staff OA's token. Reduced
# payload only ({type, replyToken, timestamp, groupId, channel}) — never
# message text, never a user/room event. See app/services/staff_oa_service.py
# and guest-feedback docs/CONTRACTS.md §15.4.
#
#   GUEST_FEEDBACK_LINE_URL
#                      Guest-feedback's internal endpoint. Production:
#                      http://feedback:4080/api/internal/line/event —
#                      container to container over the shared-nginx Docker
#                      network (no Cloudflare Access in the path), like
#                      PORTAL_DIRECTORY_URL. Not a secret.
#                      EMPTY/UNSET ⇒ nothing is ever forwarded (dark).
#   GUEST_FEEDBACK_LINE_SECRET
#                      Shared secret sent as the X-Reader-Secret header;
#                      guest-feedback compares it constant-time and answers
#                      401 on a mismatch. Same header name as READER_SECRET
#                      above, a DIFFERENT secret and a different app.
# ============================================================================


# ============================================================================
# REMOVED CONFIGURATIONS (Post-Simplification)
# ============================================================================
# The following configurations were removed during simplification:
#
# - redis_url: Redis caching eliminated 
# - api_host/api_port: Dual server eliminated, using server_host/server_port
# - feature_error_classification: Complex error handling simplified
# - feature_enhanced_circuit_breaker: Circuit breaker pattern removed
# - feature_multi_dimensional_health: Complex health monitoring simplified  
# - feature_auto_error_recovery: Auto-recovery complexity removed
# - feature_graduated_states_ui: UI state complexity simplified
# - csv_export_streaming_threshold: Streaming complexity removed
# - csv_export_max_batch_size: Batch processing simplified
# - csv_export_default_batch_size: Default export handling simplified
# - csv_export_chunk_size: Response chunking handled by FastAPI
# ============================================================================