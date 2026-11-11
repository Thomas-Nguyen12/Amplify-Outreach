"""Segment and explicit, public business-level content-marketing signals."""
from urllib.parse import urlparse

DEFAULT_QUERIES = [
    'small business owner struggling with social media content ideas',
    'independent ecommerce brand help with Instagram engagement and content calendar',
    'bootstrapped startup founder needs content marketing ideas product launch',
    'small SaaS startup founder competitor social media content strategy',
    'micro influencer struggling to find trending content ideas',
    'small creator looking for better engagement trends and posting schedule',
    'small brand competitor posts trending topics social media marketing',
    'indie founder social media growth content planning challenges',
    'creator influencer asking what to post next audience growth',
]
SMALL = ('small business', 'small brand', 'independent', 'indie', 'boutique',
         'local business', 'small shop', 'shopify', 'etsy', 'woocommerce', 'microbusiness',
         'small agency', 'small team', 'founder-led')
INFLUENCER = ('micro influencer', 'micro-influencer', 'nano influencer', 'nano-influencer',
              'influencer', 'content creator', 'creator business', 'creator economy',
              'independent creator', 'brand partnerships', 'sponsored content')
STARTUP = ('startup', 'start-up', 'pre-seed', 'seed-stage', 'bootstrapped',
           'indie hacker', 'indie founder', 'founder', 'beta launch',
           'saas', 'early-stage', 'early stage', 'new app', 'mvp')
# Topics alone do not imply buyer intent. Require specific marketing/content problems.
CONTENT_NEED = (
    'content ideas', 'audience insights', 'looking for daily social trends',
    'need help with content planning', 'struggling to post', 'struggling with content', 'need content ideas',
    'looking for content ideas', 'what should i post', 'what to post',
    'need help with social media', 'need help with content',
    'content planning challenge', 'content creation challenge',
    'social media marketing challenges', 'poor engagement', 'low engagement',
    'improve engagement', 'improving engagement', 'grow my audience',
    'growing our audience', 'need social media insights', 'need audience insights',
    'track competitors', 'competitor monitoring', 'competitor content analysis',
    'competitor social media', 'need trending topics', 'need trends for content',
    'need a content calendar', 'need help with marketing',
    'looking for social media help', 'need marketing insights',
    'looking for market research', 'need insights', 'looking for competitor',
    'looking for daily competitor', 'looking for weekly competitor',
    'market research', 'competitor analysis', 'social listening',
)
RECURRING = (
    'daily social trends', 'daily content', 'daily posts', 'every day', 'daily insights', 'daily trends',
    'daily competitor', 'weekly posts', 'weekly content', 'weekly competitor',
    'posting regularly', 'post regularly', 'content calendar', 'content schedule',
    'ongoing content', 'ongoing marketing', 'competitor monitoring',
    'track competitors', 'tracking competitors', 'daily market research',
    'weekly market research', 'regularly posting', 'ongoing competitor',
)
PUBLISHER_HOSTS = ('reddit.com','linkedin.com','youtube.com','x.com','twitter.com',
                   'instagram.com','tiktok.com','medium.com','substack.com',
                   'techcrunch.com','forbes.com','producthunt.com')

def _text(item):
    return ' '.join(str(getattr(item, name, '') or '') for name in ('description','signal')).lower()

def segment_for(item) -> str:
    text = ' '.join(str(getattr(item, name, '') or '') for name in ('business_name','description','signal')).lower()
    startup = any(term in text for term in STARTUP)
    influencer = any(term in text for term in INFLUENCER)
    small = any(term in text for term in SMALL)
    return 'startup' if startup else 'influencer' if influencer else 'small_business' if small else 'unverified'

def content_need_signals(item):
    text = _text(item)
    return [term for term in CONTENT_NEED if term in text]

def recurring_signals(item):
    text = _text(item)
    return [term for term in RECURRING if term in text]

def subscription_fit(item) -> tuple[int, list[str]]:
    matches = recurring_signals(item)
    points = 20 if len(matches) >= 2 else 12 if matches else 0
    return points, ['Recurring content/monitoring signals: ' + ', '.join(matches[:4])] if matches else ['No recurring content need observed']

def buyer_need(item) -> bool:
    return bool(content_need_signals(item))

def public_business_url(item) -> bool:
    value = item.website or item.profile_url or item.source_url
    parsed = urlparse(value)
    return parsed.scheme in ('https','http') and bool(parsed.hostname)
