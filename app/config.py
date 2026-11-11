from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Social Trend Customer Search Agent"
    database_path: str = "./data/agent.sqlite3"
    minimum_lead_score: int = Field(default=70, ge=0, le=100)
    max_results_per_query: int = Field(default=10, ge=1, le=100)
    tavily_enabled: bool = False
    tavily_api_key: str = ""
    treg_enabled: bool = False
    treg_base_url: str = "https://treg.to"
    treg_token: str = ""
    treg_auth_header: str = "X-Treg-Token"
    treg_auth_prefix: str = ""
    treg_instagram_endpoint: str = ""
    treg_tiktok_endpoint: str = ""
    treg_linkedin_endpoint: str = ""
    treg_reddit_endpoint: str = ""
    treg_x_endpoint: str = ""
    treg_youtube_endpoint: str = ""
    # Official YouTube Data API v3, separate from the Treg provider.
    youtube_enabled: bool = False
    youtube_api_key: str = ""
    youtube_search_type: str = Field(default="video", pattern="^(video|channel)$")
    youtube_enrich_videos: bool = True
    youtube_max_searches_per_run: int = Field(default=2, ge=1, le=20)
    youtube_max_searches_per_day: int = Field(default=80, ge=1, le=100)
    youtube_quota_db_path: str = "./data/youtube_quota.sqlite3"

    # Confirmed customer acquisition configuration.
    discovery_mode: str = "live_search"
    target_segments: str = "small_business,startup,influencer"
    report_frequency: str = "daily"
    subscription_currency: str = "GBP"
    subscription_interval: str = "month"
    subscription_price_gbp: str = "7"
    teaser_url: str = ""
    agent_api_key: str = ""
    minds_enabled: bool = False
    minds_builder_api_key: str = ""
    minds_research_mind_id: str = ""
    minds_timeout_seconds: int = Field(default=180, ge=30, le=600)
    minds_max_research_per_run: int = Field(default=3, ge=0, le=20)
    surreal_enabled: bool = False
    surreal_url: str = "ws://localhost:8000"
    surreal_username: str = "root"
    surreal_password: str = ""
    surreal_namespace: str = "social_trends"
    surreal_database: str = "agent"

    # Opt-in-only, autonomous email delivery. Two independent deployment gates:
    # actual hackathon organiser permission + permitted email channel. No DM API.
    outreach_autosend_enabled: bool = False
    hackathon_outreach_permission_granted: bool = False
    hackathon_permission_reference: str = ""
    outreach_email_channel_permitted: bool = False
    outreach_provider: str = Field(default="resend", pattern="^(resend|gmail)$")
    gmail_oauth_client_file: str = "credentials/gmail_oauth.json"
    gmail_token_file: str = "credentials/gmail_token.json"
    gmail_reply_poll_enabled: bool = False
    resend_api_key: str = ""
    outreach_from_email: str = ""
    outreach_reply_to: str = ""
    outreach_sender_name: str = ""
    outreach_max_per_day: int = Field(default=3, ge=0, le=20)

    def endpoint_for(self, platform: str) -> str:
        return getattr(self, f"treg_{platform}_endpoint", "")

@lru_cache
def get_settings():
    return Settings()
