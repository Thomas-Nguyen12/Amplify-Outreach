from app.models import Prospect
from app.drafts import create_draft
def test_draft_discloses_ai_without_per_message_approval():
    p=Prospect(business_name="Example Store",platform="web",source_url="https://example.com")
    _,msg=create_draft(p)
    assert "AI assistance" in msg
    assert "human review" not in msg
