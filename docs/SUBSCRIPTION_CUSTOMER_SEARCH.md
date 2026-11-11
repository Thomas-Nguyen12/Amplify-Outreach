# Subscription-first prospecting: small businesses, startups and influencers

## Decision and scope
This revises the attached 9 November draft: **the offer is now a recurring subscription**, not a one-off trend report. Price is confirmed at £7 GBP per month, with daily insight updates. This customer-search workstream **does not** collect payments, create Stripe subscriptions, send automated DMs, or deliver the analytics dashboard. Teammates own those workstreams.

## Prospect signals
- **Small business:** independently operated shop/brand, small agency, small service business; avoid treating every article mentioning a brand as proof the source is its own account.
- **Influencer:** independent content creators with public professional activity; validate actual creator identity and need, without guessing audience size.
- **Startup:** early-stage product/startup, bootstrapped project, new SaaS, indie founder *operating a business*.
- **Recurring value:** competitor tracking, daily trend updates, competitor monitoring, content planning, repeated trend monitoring. One-time launch activity alone is weak subscription evidence.
- **Demonstrated need:** public business-level statement or signal asking for market insights. The heuristic score indicates plausibility, not verified willingness to pay.
- **Do not assume:** company headcount, funding stage, buyer identity, payment capability, subscription readiness, contact permission. Research Mind should return unknown where evidence is absent.

## Run
`POST /agent/run` with `{"platforms":["web"], "queries":[]}` uses nine segment-focused default searches; set `TAVILY_ENABLED=true` and `TAVILY_API_KEY`. For supported Treg providers, configure endpoints and payload mappings from your catalogue; the adapter is still generic and not validated against all social providers.

`GET /config/targeting` describes default searches and the £7/month subscription offer and daily insights cadence.
`GET /leads` includes `segment` and `subscription_fit`.
`POST /research/{lead_id}/run` asks the configured HelloMinds Research Mind for subscription-fit evidence.
`POST /opportunities/{lead_id}` with `{"status":"interested","evidence_url":"https://...","note":"Public evidence or permissioned response ..."}` records a *manually verified* interested prospect. Allowed statuses: interested, not_interested, follow_up, converted. **Converted is a CRM label, not proof of payment.**
`GET /opportunities` is the handoff for dashboard/fulfilment teammates.

## Scoring / qualification
100 points maximum: observed need 25, small business/startup/influencer fit 20, recurring subscription value 15, commercial proxy 15, activity proxy 10, business route 10, evidence 5. A score >= `MINIMUM_LEAD_SCORE` is **not enough**: the prospect must also have target-segment and need evidence. This remains an explainable heuristic, not an AI fact-checker.

## Compliance and boundaries
Outreach is **disabled**; drafts are for human review and approved contact channels only. Suppression and known-contacts exclusions must be maintained; platform terms, applicable marketing law, and organiser approval remain prerequisites. Never use raw scraped personal contact details. Do not trust a public claim merely because a research Mind repeats it. Verify source URLs and dates before outreach.

## Shared SurrealDB
When `SURREAL_ENABLED=true`, prospect, research, and opportunity records are mirrored to SurrealDB with deterministic IDs. SQLite remains the local operational database. Sync errors are included in pipeline errors/audit logs; this is **not** a transactional cross-database guarantee. Team members should rely on SurrealDB records only when mirror health is checked. Credentials must be set as deployment secrets, never committed. Use SurrealDB Python SDK v2.

## Revenue handoff
Set subscription terms on the Stripe/dashboard side and pass only verified consent/interest to the billing workflow. The agent does **not** create recurring charges. For hackathon evidence, only real paid-and-delivered amounts count; a CRM `converted` status alone does not count. Keep organiser logs, receipts, refunds and costs in the team process.
