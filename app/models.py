from pydantic import BaseModel, Field, HttpUrl
from typing import Any

class RunRequest(BaseModel):
    queries: list[str] = Field(default_factory=list, max_length=20)
    # Empty list means all currently configured and enabled live discovery providers.
    platforms: list[str] = Field(default_factory=list)
    max_results_per_query: int = Field(default=10, ge=1, le=100)

class Prospect(BaseModel):
    business_name: str = "Unverified business"
    platform: str
    profile_url: str = ""
    website: str = ""
    description: str = ""
    signal: str = ""
    source_url: str
    source_date: str = ""
    evidence_confidence: int = Field(default=2, ge=0, le=5)
    buying_intent: int = Field(default=0, ge=0, le=30)
    niche_relevance: int = Field(default=0, ge=0, le=20)
    commercial_potential: int = Field(default=0, ge=0, le=10)
    activity: int = Field(default=0, ge=0, le=10)
    reachability: int = Field(default=0, ge=0, le=5)
    segment: str = "unverified"
    subscription_fit: int = Field(default=0, ge=0, le=20)
    score: int = 0
    priority: str = "discard"
    qualified: bool = False
    score_reasons: list[str] = []
    raw: dict[str, Any] = {}

class InterestRequest(BaseModel):
    evidence_url: HttpUrl
    note: str = Field(min_length=5, max_length=2000)
    status: str = Field(default="interested", pattern="^(interested|not_interested|follow_up|converted)$")
