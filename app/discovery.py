import httpx
from .config import get_settings
from .models import Prospect
from .treg import call_platform, TregError

def normalise_web(result):
    url=result.get("url","")
    title=result.get("title","")
    content=result.get("content","")
    return Prospect(business_name=title[:160] or "Unverified business", platform="web",
      description=content[:1200], signal=title[:300], source_url=url,
      profile_url=url, evidence_confidence=2, raw=result)

async def tavily_search(query, limit):
    s=get_settings()
    if not s.tavily_enabled or not s.tavily_api_key: return []
    async with httpx.AsyncClient(timeout=45) as c:
        r=await c.post("https://api.tavily.com/search",
          json={"api_key":s.tavily_api_key,"query":query,"search_depth":"advanced",
                "max_results":limit,"include_answer":False})
        r.raise_for_status()
        return [normalise_web(x) for x in r.json().get("results",[])]

async def discover(query, platforms, limit):
    found=[]; errors=[]
    for platform in platforms:
        try:
            if platform=="youtube_direct":
                from .youtube import search_youtube
                found.extend(await search_youtube(query, limit))
            elif platform=="web":
                found.extend(await tavily_search(query,limit))
            else:
                raw=await call_platform(platform,query,limit)
                # Provider response shapes differ. Do not guess field mappings.
                # Save raw payload for adapter mapping after endpoint schema is confirmed.
                results=raw.get("results",[]) if isinstance(raw,dict) else []
                for x in results:
                    if isinstance(x,dict) and x.get("url"):
                        found.append(Prospect(
                          business_name=x.get("business_name") or x.get("title") or "Unverified business",
                          platform=platform, profile_url=x.get("profile_url") or x.get("url"),
                          website=x.get("website",""),description=x.get("description",""),
                          signal=x.get("text") or x.get("title",""),source_url=x.get("url"),
                          source_date=str(x.get("created_at","")),evidence_confidence=2,raw=x))
        except Exception as e:
            errors.append({"platform":platform,"query":query,"error":str(e)})
    return found,errors
