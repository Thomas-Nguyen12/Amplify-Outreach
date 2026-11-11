"""Unsent prospect-specific marketing drafts. No prices, no unsupported AI claims."""
import re
from .config import get_settings

_PRICE = re.compile(r'(?i)(?:£|\$|€)\s*\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s*(?:gbp|usd|eur)\b|\b\d+(?:[.,]\d+)?\s*/\s*(?:month|mo|year|yr)\b')


def create_draft(item, *, assessment=None):
    """A verified finding changes the message, but missing evidence never creates a claim.

    Pipeline handles eligibility; this helper also checks findings for direct callers.
    No outbound action is performed.
    """
    s = get_settings()
    name = item.business_name if item.business_name != 'Unverified business' else 'your team'
    group = {'startup': 'startups', 'small_business': 'small businesses',
             'influencer': 'independent creators'}.get(item.segment, 'small teams')
    verified = (assessment or {}).get('verified_findings') or []
    verified = [f for f in verified if isinstance(f, dict)
                and isinstance(f.get('quote'), str) and isinstance(f.get('source_url'), str)]
    intro = f'I came across {name} and your public work.'
    if verified:
        finding = verified[0]
        # Only a previously validated quote should reach this point; strip accidental pricing.
        quote = _PRICE.sub('[price omitted]', finding['quote'].strip())[:170]
        intro = f'I noticed this point in your public content: “{quote}” (source: {finding["source_url"]}).'
    teaser = (f' You can preview it here: {s.teaser_url}' if s.teaser_url else ' A sample is available on request.')
    subject = f'Daily content and trend ideas for {name}'
    message = (
        f'Hi {name} team,\n\n'
        f'{intro}\n\n'
        f'We are building a daily insights subscription for {group}, including '
        'competitor and hot-topic monitoring and ready-to-post content suggestions. '
        f'Would seeing a sample be useful?{teaser}\n\n'
        'This message was prepared with AI assistance.\n'
        'If you would prefer no further contact, please let us know.\n'
    )
    # Defence-in-depth against user-supplied brand names, URLs or excerpts carrying a price.
    return _PRICE.sub('[price omitted]', subject), _PRICE.sub('[price omitted]', message)
