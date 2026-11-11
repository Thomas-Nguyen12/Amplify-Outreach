from app.hellominds import research_prompt
from app.surreal_store import _record_key


def test_research_prompt_is_evidence_based():
    prompt = research_prompt({'business_name':'Example Shop','source_url':'https://example.org'})
    assert 'Example Shop' in prompt
    assert 'PUBLIC source URLs' in prompt
    assert 'Do not fabricate sources' in prompt


def test_surreal_keys_are_deterministic():
    assert _record_key('example.com') == _record_key('example.com')
    assert _record_key('example.com') != _record_key('another.com')
