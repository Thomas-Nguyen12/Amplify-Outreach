"""Validate final Research Mind reports and correlate claims with captured sources.

A Minds acknowledgement is pending, never completed. AI-generated citations cannot
substitute for captured, independently available source text.
"""
import json
import re
from urllib.parse import urlsplit, urlunsplit
from .scoring import score_item
from .targeting import CONTENT_NEED


def _canon_url(url):
    p = urlsplit(str(url or '').strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower().removeprefix('www.'), p.path.rstrip('/'), '', ''))



def parse_assessment(reply):
    """Parse structured HelloMinds reports from JSON or supported wrappers."""
    if not isinstance(reply, str):
        return None

    text = reply.strip()

    # HelloMinds sometimes wraps JSON inside HTML <pre> tags.
    text = re.sub(
        r'^<pre(?:\s[^>]*)?>\s*',
        '',
        text,
        count=1,
        flags=re.I,
    )
    text = re.sub(
        r'\s*</pre>\s*$',
        '',
        text,
        count=1,
        flags=re.I,
    )

    # Support Markdown code fences, including inside <pre> tags.
    text = re.sub(
        r'^```(?:json)?\s*',
        '',
        text,
        count=1,
        flags=re.I,
    )
    text = re.sub(
        r'\s*```\s*$',
        '',
        text,
        count=1,
    )

    try:
        obj = json.loads(text.strip())
    except (ValueError, TypeError):
        return None

    return obj if isinstance(obj, dict) else None


def classify_research(research):
    """Return completed/pending/invalid. Completed requires a final structured report.

    This is validation of response *format*, not an assertion that the model has
    independently checked anything. Such evidence is verified separately below.
    """
    if research.get('pending') and not research.get('reply'):
        return 'pending'
    data = parse_assessment(research.get('reply', ''))
    if not data:
        return 'pending' if str(research.get('reply', '')).strip() else 'invalid'
    if str(data.get('status', '')).lower() in ('pending', 'in_progress', 'started'):
        return 'pending'
    if (data.get('status') != 'completed'
            or not isinstance(data.get('summary'), str) or not data['summary'].strip()
            or not isinstance(data.get('evidence'), list)
            or not isinstance(data.get('limitations'), list)
            or not isinstance(data.get('content_challenges'), list)):
        return 'invalid'
    return 'completed'


def apply_research_assessment(item, research):
    """Use only verbatim quotes found in captured source text; no AI-only score bump."""
    state = classify_research(research)
    result = {'research_reviewed': state == 'completed', 'research_status': state,
              'evidence_accepted': 0, 'status': 'research_' + state,
              'verified_findings': []}
    if state != 'completed':
        return result
    data = parse_assessment(research['reply'])
    # Source dates are not proof; only original captured text/URLs can corroborate.
    captured = [(item.source_url, item.signal or ''),
                (item.profile_url, item.description or '')]
    findings = []
    for entry in data['evidence'][:20]:
        if not isinstance(entry, dict):
            continue
        quote = str(entry.get('quote') or '').strip()
        url = _canon_url(entry.get('source_url'))
        if len(quote) < 12 or not url:
            continue
        if not any(url == _canon_url(source_url) and quote.casefold() in source_text.casefold()
                   for source_url, source_text in captured):
            continue
        if not any(term in quote.casefold() for term in CONTENT_NEED):
            continue
        if any(f['quote'].casefold() == quote.casefold() for f in findings):
            continue
        findings.append({'source_url': entry['source_url'], 'quote': quote})
    result['evidence_accepted'] = len(findings)
    result['verified_findings'] = findings[:3]
    result['status'] = 'completed_with_correlated_evidence' if findings else 'completed_no_verified_evidence'
    # Scoring continues to be deterministic from the original public evidence.
    score_item(item)
    if findings:
        item.score_reasons.append('HelloMinds verified quotes against captured source text; no AI-only score boost.')
    return result
