from app.models import Prospect
from app.compliance import check_prospect
from app.database import init_db
def test_outreach_never_enabled():
    init_db()
    p=Prospect(business_name="Example Store",platform="web",source_url="https://example.com",
      description="Independent online shop")
    result=check_prospect(p)
    assert result["eligible_for_research"]
    assert result["eligible_for_outreach"] is False
