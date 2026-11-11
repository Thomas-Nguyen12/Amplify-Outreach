> **11 November 2026:** Outreach drafts now omit pricing entirely. HelloMinds must return a final structured JSON report before the API marks research complete. Personalised prospect-specific claims require source-correlated quotes; incomplete acknowledgements remain pending. Prior persisted drafts are not retroactively changed. See [Customer Acquisition / Research-First](docs/CUSTOMER_ACQUISITION_RESEARCH_FIRST.md).

> **Current customer-acquisition implementation (Nov 2026):** This project targets **small businesses, early-stage startups and influencers** for a **£7/month subscription** offering daily social trend insights, competitor and hot-topic monitoring, and ready-to-post content suggestions. **HelloMinds can research plausible leads before final draft generation, including initially unqualified YouTube leads.** No outbound messages are sent. See [Customer Acquisition / Research-First](docs/CUSTOMER_ACQUISITION_RESEARCH_FIRST.md) for the up-to-date workflow, diagrams, scoring rubric and live HelloMinds test commands. Older historical sections below describe prior iterations.

> **Detailed architecture and data flows:** [docs/ARCHITECTURE_AND_DATA_FLOWS.md](docs/ARCHITECTURE_AND_DATA_FLOWS.md) documents every major module, the live pipeline, the offline and HelloMinds simulations, Daytona sandbox execution, database schemas, log formats and limitations. Includes Mermaid diagrams.

# Confirmed configuration — Live discovery / £7 per month / daily insights

**Target groups:** small startups, small businesses and independent influencers.
**Offer:** £7 GBP billed monthly, delivering daily social trend insights (delivery and payment handled in separate team workstreams).
**Discovery mode:** `live_search`; search queries and leads come from configured live Tavily and/or Treg providers, not synthetic fixtures.

1. `cp .env.example .env` and add `TAVILY_API_KEY` for public-web search. By default `TAVILY_ENABLED=true`, so live searching works only after a valid API key is added.
2. Optional: add verified Treg endpoints, provider schemas and commercial permissions before enabling Treg.
3. `POST /agent/run` with `{"queries":[],"platforms":[],"max_results_per_query":5}` searches all **configured and enabled** live providers using segment-specific defaults. Explicit `platforms` can limit the search. If none is configured the API returns a clear error, not fake leads.
4. `GET /config/targeting` shows the confirmed segments, £7/month and daily insight frequency. `GET /config/platforms` shows provider readiness.
5. Keep outbound outreach disabled; source evidence and compliance review are required. Live search does not mean live messaging.

**Note:** The codebase does not implement daily report generation, scheduling or Stripe billing; those remain other team workstreams. Influencer search is heuristic and requires verification that a public creator profile is professional and reachable by a permitted business channel.

---

# Customer Search Agent — Subscription Edition

**Updated target:** small businesses, early-stage startups and influencers. **Updated offer:** £7/month with daily trend insights. Customer search and research only; payment and dashboard fulfilment remain separate workstreams. See [`docs/SUBSCRIPTION_CUSTOMER_SEARCH.md`](docs/SUBSCRIPTION_CUSTOMER_SEARCH.md) for the revised contract and API details.

# Social Trend Customer Search Agent

A runnable, cautious MVP for discovering **small e-commerce businesses** from permitted public sources, scoring evidence-backed prospects, and preparing outreach drafts. It does **not** send messages.

## Architecture
- FastAPI application and CLI runner
- Treg gateway adapter (configurable endpoint mapping; no guessed provider endpoint names)
- Tavily public-web discovery fallback/supplement
- SQLite storage, deduplication, suppression list, audit events
- deterministic explainable scoring
- draft-only outreach with compliance gates
- provider capability registry so unsupported or unapproved APIs remain disabled

## Important Treg setup
Treg endpoint names and request schemas must be copied from the current Treg catalogue for the providers you actually enable. This project deliberately does not invent endpoint names or payload schemas.

Set `TREG_BASE_URL`, `TREG_TOKEN`, then configure `TREG_INSTAGRAM_ENDPOINT`, `TREG_TIKTOK_ENDPOINT`, `TREG_LINKEDIN_ENDPOINT`, `TREG_REDDIT_ENDPOINT`, `TREG_X_ENDPOINT`, and `TREG_YOUTUBE_ENDPOINT` using exact catalogue endpoint identifiers. The generic Treg adapter passes the configured JSON payload to `/call/{endpoint}`. Verify the current auth header and route against your Treg account docs before live use; the default header here is configurable.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env. Start with TREG_ENABLED=false and TAVILY_ENABLED=true.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open http://localhost:8000/docs

## Run a search
```bash
curl -X POST http://localhost:8000/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"queries":["small Shopify skincare brand product launch","independent fashion brand new collection"],"platforms":["web"],"max_results_per_query":5}'
```
To call Treg, configure an exact endpoint and payload template for a platform and enable it. The generic `/agent/run` uses only configured adapters.

## Configure Treg endpoints
For each platform, set the endpoint identifier from your Treg catalogue and set a JSON payload template in `config/platform_payloads.json`. The template must match the selected provider's documented schema. Example is intentionally empty:
```json
{
  "instagram": {},
  "tiktok": {},
  "linkedin": {},
  "reddit": {},
  "x": {},
  "youtube": {}
}
```
The request body sent to Treg is the configured payload with `query` and `limit` merged in. Some provider operations may require different field names; adjust `app/treg.py` for the exact schema. Confirm the route/auth header in your Treg documentation before use.

## Safety and compliance
- Use only official APIs or providers whose access and commercial-use rights you have verified.
- Treg is a gateway, not a permission bypass. Follow each platform's terms, API limits, retention rules, and commercial-use terms.
- Do not scrape logged-in pages, bypass access controls, harvest personal contact details, or send unsolicited automated messages.
- Store business-level evidence and source URLs; minimise personal data.
- Use suppression lists, deduplication, source timestamps, and human review.
- `OUTREACH_ENABLED` is intentionally not implemented as a send capability. This project only creates drafts.
- TikTok Research API is not a general commercial prospecting API. Do not use it for this commercial project unless TikTok explicitly authorises your intended use.
- LinkedIn and Instagram access is limited to approved products/permissions. Do not assume broad public search is available.

## Tests
```bash
pytest -q
```

## API endpoints
- `GET /health`
- `GET /config/platforms`
- `POST /agent/run`
- `GET /leads`
- `GET /leads/{lead_id}`
- `GET /drafts`
- `POST /suppression`
- `GET /metrics`
- `GET /export/leads.csv`

## What this MVP does not include
No guarantee every social platform has a suitable Treg search endpoint for your account. It does not include a real Treg provider schema, platform app approval, automated message sending, paid checkout, Minds integration, SurrealDB, Daytona deployment, or a production-grade LLM. Those require account-specific setup and verification.

## HelloMinds Research Mind + SurrealDB (new)

This version adds an **official HelloMinds client-library bridge** and **optional SurrealDB mirroring**. SQLite remains the operational database and is not removed. No live external credentials were available during development, so the live services were not integration-tested.

1. Install Python requirements (`pip install -r requirements.txt`) and Node.js **22+**.
2. Install the official HelloMinds client: `cd bridge && npm install && cd ..`.
3. In the [HelloMinds Builder console](https://build.hellominds.ai/en/docs), create a Builder API key and create or select a **Research Mind**. Find its UUID using `minds list` or the Builder console. This is an account-specific ID, not the label `research`.
4. Copy `.env.example` to `.env`; set `MINDS_ENABLED=true`, `MINDS_BUILDER_API_KEY` and `MINDS_RESEARCH_MIND_ID`. Never commit `.env`.
5. Start SurrealDB v2+ (for example `docker run --rm -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass YOUR_PASSWORD`), then set `SURREAL_ENABLED=true`, `SURREAL_URL`, `SURREAL_USERNAME`, `SURREAL_PASSWORD`, namespace and database. Use TLS and scoped credentials for cloud deployments.
6. Run `uvicorn app.main:app --reload`. Use `POST /agent/run` to discover, score and optionally research up to `MINDS_MAX_RESEARCH_PER_RUN` new qualified leads, or `POST /research/{lead_id}/run` to research a specific stored lead. Read briefs with `GET /research` or `GET /research/{lead_id}`.

**Behavior:** Research Mind receives a single prospect's public business details and a prompt requiring sources, uncertainty, and a free teaser idea. Its returned text is stored in `research_briefs` (SQLite) and mirrored to SurrealDB `research_briefs`; lead records are mirrored to SurrealDB `prospects`. Mirroring errors are reported in `/agent/run` without discarding the SQLite record. The manual research endpoint logs mirror errors in the audit log. Suppression, drafts and audit events remain in SQLite only. This is **not a full SurrealDB migration**.

**Limitations:** HelloMinds research depends on the Mind's equipped skills, cognition balance and accessible tools; it is not a replacement for Treg/social platform API access. The Mind's answer is unstructured text requiring human verification before sales use. Each Research Mind request may consume cognition credits. Automatic research uses a per-run cap, but manual calls can be repeated. The Node bridge uses a stable per-lead conversation alias; a timeout may mean the request was sent but the answer was not received, so inspect Minds history before retrying. The system never sends sales outreach. No production access controls are included on the FastAPI endpoints; do not expose this server publicly without authentication.

Official references: https://build.hellominds.ai/en/docs/get-started/client-library and https://surrealdb.com/docs/reference/python

## Local simulated customers and outreach regression tests

A fully offline simulation is now included. It tests the **same scoring, qualification, compliance and draft-building functions** as the real agent against eight fictional business/startup/influencer records, simulates message delivery locally (never actually sends), records scripted buyer responses, and exports customer/message/response/audit logs.

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m scripts.run_simulation --output-dir outputs/simulation
```

Logs are in `outputs/simulation/<run_id>/` (`customers.csv`, `messages.csv`, `responses.csv`, `events.jsonl`, `summary.json`). Simulation records use `data/simulation.sqlite3` rather than the production CRM and explicitly record actual outreach, revenue and subscriptions as **zero**. The simulator needs no API keys; it never calls Treg, Tavily, HelloMinds, SurrealDB, Stripe, or social media messaging APIs. Read `docs/LOCAL_SIMULATION.md` for Daytona setup and limitations.

## NEW: HelloMinds-powered synthetic research in Daytona

This release adds a live **Research Mind integration test using fictional small businesses, startups and influencers**. The existing offline customer simulator remains unchanged. Set `MINDS_ENABLED=true`, a valid `MINDS_BUILDER_API_KEY` and `MINDS_RESEARCH_MIND_ID`, then run:

```bash
cd bridge && npm install && cd ..
python -m scripts.run_minds_simulation --max-research 2
```

The above sends fictional research briefs **to HelloMinds**, not to prospective customers. Customer replies in the logs remain scripted. No Stripe charges, real outreach, SurrealDB writes or live prospect discovery occur. Results and research replies are exported in a separate simulation database.

For a Daytona sandbox runner, log files and setup steps, see `docs/HELLOMINDS_DAYTONA_SIMULATION.md`. Disable any outbound action tools on your HelloMinds Mind before running the test.

## SurrealDB persistence hardening (new)

See [`docs/SURREALDB_END_TO_END_PERSISTENCE.md`](docs/SURREALDB_END_TO_END_PERSISTENCE.md)
for the cross-Daytona-sandbox test, canonical prospect identity, suppression
persistence, HelloMinds retry rules and the opt-in real-database CRUD test.
The local tests never access live SurrealDB. `GET /persistent/leads` provides
canonical lead records between sandbox restarts when SurrealDB is enabled.

## Daytona sandbox deployment (updated November 2026)

See [`docs/DAYTONA_DEPLOYMENT_READINESS.md`](docs/DAYTONA_DEPLOYMENT_READINESS.md).
The current Daytona SDK compatible simulator is `scripts/run_daytona.py`.
It supports isolated offline tests and optional HelloMinds research on fictional
prospects. It does **not** automatically schedule or run live customer discovery.
Recommended starting allocation: 2 vCPU, 4 GiB RAM, 8 GiB disk, no GPU.


## Direct YouTube Data API v3 discovery (new)

The project now supports official YouTube channel/video searches with `YOUTUBE_ENABLED=true`, `YOUTUBE_API_KEY` and `platforms:["youtube_direct"]`. This is independent of the Treg `youtube` connector. Channel/video metadata is normalised, scored, deduplicated by channel ID and passed into the existing SurrealDB/HelloMinds path. The connector is fully mocked in CI tests; a live smoke test is opt-in and has not been executed against your Google credentials.

**Start here:** [`docs/YOUTUBE_DIRECT_INTEGRATION.md`](docs/YOUTUBE_DIRECT_INTEGRATION.md). The guide includes the annotated Mermaid workflow, configuration, quotas, privacy cautions, smoke tests, and Daytona limitations.

## Durable HelloMinds completion / retry recovery (latest)

The latest acquisition implementation starts research with a stable conversation alias and stores **pending** jobs in SurrealDB with the HelloMinds history fingerprint. Use `POST /research/persistent/reconcile?limit=2` or `python -m scripts.reconcile_research --limit 2` to poll that same conversation without resending the prompt. `GET /research/persistent/pending`, `GET /persistent/research`, and `GET /persistent/drafts` expose durable state across new Daytona instances. All outbound customer messaging remains disabled and all newly generated customer-facing drafts omit pricing.

The historical DPL Seller Academy Mind conversation CF655841 completed outside the old timeout. Use the opt-in manual report import route `POST /research/persistent/import` with `examples/dpl_seller_academy_import.json` **after checking the reconstructed data against the conversation**. The Markdown-corrupted citations in the pasted JSON must not be taken as verified source evidence. See [docs/HELLOMINDS_DURABLE_RECOVERY.md](docs/HELLOMINDS_DURABLE_RECOVERY.md) for installation, sandbox recovery, limitations and smoke tests.

## Optional automated email outreach (explicit opt-in only)

New implementation: `app/outreach.py`, `scripts/dispatch_outreach.py`,
`sql/outreach_tables.surql` and `docs/AUTONOMOUS_EMAIL_OUTREACH.md`.
**No per-message human approval is required** once configured; however, email
sending remains OFF by default and is limited to independently documented
recipient opt-ins, authorised hackathon email channel, complete evidence-backed
research, qualification, suppression safeguards and strict durable de-duplication.
A public YouTube business email alone is NOT permission. There is no automatic
social DM/comment sending and no automatic inbound mailbox reader yet.
Use `GET /outreach/status` for exact readiness checks.

## Gmail delivery and opt-out reconciliation (optional)

The acquisition agent now supports `OUTREACH_PROVIDER=gmail` as an alternative to Resend. It reuses the existing persistent opt-in, deduplication, daily-cap, research and outreach checks. Gmail OAuth requires a local private credentials JSON, token renewal and a separate authorisation for read-only reply monitoring. **Automatic sending and inbox polling are disabled by default**, and the software cannot establish marketing consent by itself.

**Detailed configuration and testing:** [docs/GMAIL_INTEGRATION.md](docs/GMAIL_INTEGRATION.md).
