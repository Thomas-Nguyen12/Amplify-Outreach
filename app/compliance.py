from urllib.parse import urlparse
from .database import is_suppressed

def check_prospect(item, *, suppressed=None):
    reasons=[]
    if not item.source_url or urlparse(item.source_url).scheme not in ("http","https"):
        reasons.append("Missing or invalid public evidence URL")
    if not item.business_name or item.business_name == "Unverified business":
        reasons.append("Prospect identity not verified")
    identity=(item.website or item.profile_url or item.source_url).lower().rstrip("/")
    if (is_suppressed(identity) if suppressed is None else suppressed):
        reasons.append("Identity is on suppression list")
    if not item.description and not item.signal:
        reasons.append("Insufficient evidence")
    return {"eligible_for_research": not reasons, "eligible_for_outreach": False,
            "reasons": reasons + ["Human review and approved contact route required; sending is disabled"]}
