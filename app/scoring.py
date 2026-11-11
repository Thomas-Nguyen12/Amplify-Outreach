"""Explainable 100-point customer-acquisition scoring; not a purchase predictor."""
from datetime import datetime, timezone
from .targeting import segment_for, subscription_fit, content_need_signals
from .config import get_settings

WEIGHTS = {
    'content_pain': 30, 'segment_fit': 20, 'recurring_content_need': 20,
    'commercial_proxy': 10, 'recent_activity': 10, 'public_business_route': 5,
    'evidence_confidence': 5,
}

def score_item(item):
    segment = segment_for(item)
    needs = content_need_signals(item)
    pain = min(30, len(needs) * 10)
    niche = 20 if segment != 'unverified' else 0
    recurring, recurring_reasons = subscription_fit(item)
    commercial = 10 if item.website and segment != 'unverified' else 5 if segment != 'unverified' else 0
    activity = 3
    if item.source_date:
        try:
            dt = datetime.fromisoformat(item.source_date.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days
            activity = 10 if 0 <= days <= 30 else 3
        except (ValueError, AttributeError, TypeError):
            activity = 3
    reach = 5 if item.website else 3 if item.profile_url else 0
    confidence = min(5, item.evidence_confidence)
    total = min(100, pain + niche + recurring + commercial + activity + reach + confidence)
    enabled = {part.strip() for part in get_settings().target_segments.split(',') if part.strip()}
    qualified = total >= get_settings().minimum_lead_score and segment in enabled and bool(needs)
    item.segment, item.subscription_fit, item.buying_intent = segment, recurring, pain
    item.niche_relevance, item.commercial_potential = niche, commercial
    item.activity, item.reachability, item.score, item.qualified = activity, reach, total, qualified
    item.priority = 'high' if qualified and total >= 80 else 'medium' if qualified else 'review' if total >= 40 else 'discard'
    item.score_reasons = [
        f'Segment: {segment} ({niche}/20)',
        f'Observed content/social pain: {pain}/30' + (f' ({", ".join(needs[:4])})' if needs else ' (not observed)'),
        f'Recurring content fit: {recurring}/20', *recurring_reasons,
        f'Commercial proxy: {commercial}/10', f'Recent activity: {activity}/10',
        f'Business reachability: {reach}/5', f'Evidence confidence: {confidence}/5',
        'Scores estimate product fit, NOT intent to purchase; verify identity, need and permitted contact route.',
    ]
    if item.platform == 'youtube_direct':
        channel_id = item.raw.get('channel_id') if isinstance(item.raw, dict) else None
        video_url = item.raw.get('video_url') if isinstance(item.raw, dict) else None
        item.score_reasons.extend([
            f'YouTube channel ID: {channel_id or "not available"}',
            f'Video evidence: {video_url or "not available"}',
            'Channel subscriber counts and video topics are NOT buyer-intent evidence.',
            'A channel discussing founders is not necessarily a startup buyer.',
        ])
    return item
