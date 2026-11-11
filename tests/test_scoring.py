from app.models import Prospect
from app.scoring import score_item
def test_scoring_is_bounded():
    p=Prospect(business_name="Shopify skincare brand",platform="web",
      description="Looking for product research and trending products",source_url="https://example.com")
    score_item(p)
    assert 0 <= p.score <= 100
    assert p.buying_intent == 0  # Product research alone is not content-marketing pain.
