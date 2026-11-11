import httpx
from .config import get_settings

PLATFORMS = ["instagram","tiktok","linkedin","reddit","x","youtube"]

class TregError(RuntimeError): pass

async def call_platform(platform: str, query: str, limit: int):
    s=get_settings()
    if not s.treg_enabled: raise TregError("Treg integration is disabled")
    if not s.treg_token: raise TregError("TREG_TOKEN is not configured")
    endpoint=s.endpoint_for(platform)
    if not endpoint: raise TregError(f"No verified Treg endpoint configured for {platform}")
    # The endpoint identifier and payload shape must come from your live Treg catalogue.
    headers={s.treg_auth_header: f"{s.treg_auth_prefix}{s.treg_token}",
             "Content-Type":"application/json"}
    payload={"query":query,"limit":limit}
    async with httpx.AsyncClient(timeout=45) as client:
        r=await client.post(f"{s.treg_base_url.rstrip('/')}/call/{endpoint}",
                            headers=headers,json=payload)
        r.raise_for_status()
        return r.json()
