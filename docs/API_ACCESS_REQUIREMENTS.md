# Social platform API access checklist

This project is a commercial customer-discovery and analytics prototype. Platform approval and commercial-use rights must be checked before enabling any connector. A gateway such as Treg does not grant permission beyond the underlying provider/platform terms.

| Platform | Developer setup / credentials | Access and practical limitations |
|---|---|---|
| Instagram | Meta developer account; Meta app; eligible Instagram professional account; access token; required permissions and any app review/business verification. | Instagram APIs are not a general search engine for every public profile/post. Use only endpoints available to your app and approved permissions. Verify current Graph API product and eligibility. |
| TikTok | TikTok for Developers account; registered app; product/API approval; app credentials and tokens as specified by product. | Commercial Content API access and other products have distinct eligibility and data scope. Research API is restricted and is not a general commercial prospecting route. Do not use it for this commercial project absent explicit authorisation. |
| LinkedIn | LinkedIn developer account; registered app; OAuth 2.0 client credentials; approved products and scopes; review/partner approval where required. | Most APIs are permissioned. Do not assume API access to search all members, profiles or posts. Use only data and use cases granted to the app. |
| Reddit | Reddit developer account; registered OAuth application; client ID/secret; redirect URI; user agent; OAuth token. | Observe API rate limits, developer terms, retention and deletion rules. Confirm commercial-use permission or agreement for the intended use before production. |
| X | X developer account; project/app; Bearer Token or OAuth credentials; paid/eligible API access tier as needed. | Search endpoints, archive depth, quotas and price depend on current access tier. Recent search is limited to a recent window; full archive requires eligible access. |
| YouTube | Google account; Google Cloud project; YouTube Data API v3 enabled; API key or OAuth credentials; quota allocation. | Public video/channel metadata search is available, but quota limits apply. Follow YouTube API Services Terms, Developer Policies, data refresh/deletion and storage requirements. |

## Recommended order
1. Reddit and YouTube (clear developer onboarding; still check commercial terms and quota).
2. X (confirm cost/access tier).
3. Instagram (confirm eligible API product and permissions).
4. LinkedIn (confirm approved use case and scopes).
5. TikTok (select a suitable commercially authorised product; do not rely on Research API).

## Before turning on any platform
- Record the exact Treg provider, endpoint identifier, schema, rate limits, price and commercial rights.
- Confirm the endpoint is an official API or an authorised data provider.
- Confirm platform terms allow the intended prospecting and paid analytics use.
- Configure the endpoint and payload mapping; test with low-volume requests.
- Store secrets in deployment secrets, never source control.
- Collect business-level data and public evidence; avoid sensitive personal data.
- Respect deletion, retention, opt-out and suppression requirements.
