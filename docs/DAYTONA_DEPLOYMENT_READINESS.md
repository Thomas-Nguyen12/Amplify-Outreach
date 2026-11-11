# Daytona deployment and compute sizing (10 November 2026)

## Readiness verdict

**Ready for local tests and Daytona *sandbox smoke tests*, not yet verified for unattended production.**
The Python/Node application, synthetic customer fixtures, pytest suite, live-search
adapters for Tavily/Treg, HelloMinds bridge, and SurrealDB persistence store are
included. The bundled Daytona runner has been updated for the current synchronous
Daytona Python SDK (`daytona.create`, `sandbox.process.exec`, `sandbox.fs`,
`daytona.delete`). This runner is not yet tested against an actual Daytona account.

There is **no direct YouTube Data API v3 adapter** yet, despite the existing
YouTube endpoint configuration through Treg. Obtaining a Google API key does not
activate direct YouTube searches in this version.

### Recommended compute

| Workload | vCPU | RAM | Disk | GPU |
|---|---:|---:|---:|---|
| Basic synthetic tests | 1 | 1 GiB | 3 GiB | No |
| Hourly agent, low concurrency | 1 | 2 GiB | 5 GiB | No |
| First full Daytona test, Python + Node + pip/npm installs | **2** | **4 GiB** | **8 GiB** | No |
| Larger batches / concurrent jobs | 4 | 8 GiB | 10 GiB | No |

These are capacity estimates rather than measurements. External APIs perform AI
inference. Local compute is primarily FastAPI, JSON processing, SQLite cache,
Node bridge, network requests, and pytest. Actual storage depends on installed
packages, logs and number of records. Daytona's documented standard `daytona-medium`
snapshot has 2 vCPU, 4 GiB, 8 GiB; the default `daytona-small` has 1 vCPU,
1 GiB, 3 GiB. See https://www.daytona.io/docs/sandboxes.

## 1. Prepare on your own computer

Install Python dependencies and the current Daytona SDK:

```bash
python -m pip install -r requirements.txt
python -m pip install daytona
python -m pytest -q
```

Set `DAYTONA_API_KEY` in your terminal or untracked `.env`, **not in source
control**. Do not submit credentials in chat or include a `.env` in a project
archive.

## 2. Run Daytona offline simulation

From the project root, with the downloaded ZIP at a known path:

```bash
python -m scripts.run_daytona \
  --zip /path/to/social-trend-agent-daytona-ready.zip \
  --mode offline \
  --output-zip ./daytona-offline-logs.zip
```

This creates a `daytona-medium` sandbox, uploads the source ZIP without local
`.env`, installs Python dependencies, runs pytest, executes a synthetic-customer
simulation, downloads a log ZIP, and deletes the sandbox.

## 3. Optionally test real HelloMinds research against fictional data

Use `MINDS_BUILDER_API_KEY` and `MINDS_RESEARCH_MIND_ID` from your own untracked
`.env`; the research mode may consume API credits and must use a Daytona snapshot
with Node.js 22+.

```bash
python -m scripts.run_daytona \
  --zip /path/to/social-trend-agent-daytona-ready.zip \
  --mode minds \
  --max-research 2 \
  --output-zip ./daytona-minds-logs.zip
```

The default snapshot may not include Node 22+. Build/provide a compatible
snapshot if the Node check fails. HelloMinds research subjects are fictional;
responses from simulated customers are scripted. **No messages are sent**.

## 4. Live discovery in Daytona: prerequisites

For a real customer search, configure:

- Tavily API key (web discovery), and/or Treg token and *verified* social provider endpoints.
- HelloMinds Mind ID and Builder API key for optional qualified-lead research.
- SurrealDB native `wss://`/`https://` URL, database credentials, namespace and database.
- Initialise schema for `prospects`, `suppression`, `research_briefs`, and
  `outreach_drafts` *in the database used by the pipeline*.
- Use a Daytona or external scheduler to trigger the **real** `/agent/run` API.
  The `run_daytona.py` script in this ZIP is a **simulation runner only**;
  it does not trigger production discovery.
- Do not assume any direct YouTube API feature; that adapter still needs building.
- Keep automated outreach disabled. Drafts are not delivery events.
- Secure credentials, run locks, rate limits, cost limits, monitoring, and
  idempotent cross-sandbox persistence are needed for production.

## 5. Important caveats

- The local automated tests pass using mocked integrations. A separate live
  SurrealDB test was reported as passed by the user, but Daytona and live
  provider-to-provider execution have not yet been demonstrated.
- SurrealDB `PersistentStore` opens one connection per operation. User-reported
  roughly 10–11-second single-operation timings indicate performance needs work.
- SQLite is a local API cache; SurrealDB retains canonical discovery identities
  and suppression when enabled. Do not delete a sandbox relying on SQLite alone.
- Schema migrations and existing SQLite-data migration must be planned before
  production. This archive contains `scripts/migrate_sqlite_to_surreal.py`.
- No Stripe recurring billing, automatic daily subscriber-report delivery,
  automated outreach or external hourly scheduler is implemented in this package.
- Source material and tests are included; the archive intentionally omits
  working SQLite databases, secrets, Python virtual environments and caches.


### Direct YouTube discovery in Daytona

The direct adapter is `app/youtube.py` (`youtube_direct`), activated with `YOUTUBE_ENABLED=true` and `YOUTUBE_API_KEY`. It uses HTTPX; no extra SDK is required. See `docs/YOUTUBE_DIRECT_INTEGRATION.md` for configuration and tests. Configure keys through the sandbox's secret injection. The local YouTube quota ledger does not persist between **new ephemeral sandboxes**, so a shared central quota gate is required before using parallel/hourly ephemeral runners with production API access.
