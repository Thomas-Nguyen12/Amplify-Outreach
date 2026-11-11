# Offline customer simulation + pytest coverage

## Purpose
This test harness simulates **small businesses, early-stage startups and influencers** evaluating a **£7/month social trend analytics subscription with daily insights**. It runs locally or inside a Daytona cloud sandbox. It does **not** send messages, create Stripe payments, query Tavily/Treg, call HelloMinds, or write into SurrealDB.

Simulation and real CRM use different SQLite files/tables. The simulator calls the actual `score_item`, `check_prospect` (with a synthetic suppression flag), and `create_draft` functions, then generates responses from explicitly declared synthetic personas. Responses are scripted test fixtures, **not an LLM prediction of actual willingness to pay**.

## Run locally
From the extracted `social-trend-customer-agent/` directory:

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m scripts.run_simulation --output-dir outputs/simulation
```

No API keys are required for these commands. All example domains end in `.example` and are not actual prospects.

Optional custom dataset:

```bash
python -m scripts.run_simulation --fixtures fixtures/synthetic_customers.json --threshold 75 --db data/simulation.sqlite3 --output-dir outputs/my-experiment
```

Every run gets a unique ID and produces:

- `customers.csv`: each synthetic customer, assigned segment, score, qualification, suppression flag
- `messages.csv`: message subjects/bodies with `delivery_status=simulated_sent` (**not really sent**)
- `responses.csv`: synthetic response category and response text, including no-response
- `events.jsonl`: append-only per-run timeline: evaluated -> skipped or simulated message -> synthetic response
- `summary.json`: totals plus explicit zero values for actual messages, subscriptions and revenue

The SQLite database `data/simulation.sqlite3` retains runs independently of the real `DATABASE_PATH`. Messages and responses are not imported into `prospects`, `drafts`, or `subscription_opportunities`.

## Sample scenarios

`SIM-001` independent shop: interested; `SIM-002` startup: asks question; `SIM-003` creator: interested; `SIM-004` cafe: declines; `SIM-005` startup: no response; `SIM-006` store without clear analytics need: not qualified; `SIM-007` unverified business: excluded; `SIM-008` suppressed business: excluded.

These outcomes are deliberately scripted and repeatable so regression tests can assert behaviour. In the sample scenario, 8 records yield 5 simulated sends (2 interested, 1 question, 1 decline, 1 no response) and 3 exclusions.

## Run inside Daytona

1. Create a Daytona sandbox using your Daytona account and upload/unzip the project folder; alternatively clone your own repository inside the sandbox.
2. `cd` into `social-trend-customer-agent`.
3. Execute the same `pip install`, `pytest` and `python -m scripts.run_simulation` commands shown above.
4. Inspect `outputs/simulation/<run_id>/` or download the generated logs from the sandbox.
5. Delete the sandbox after testing to avoid unnecessary charges.

The core simulation is platform-independent and does not depend on Daytona. A Daytona sandbox is an **execution environment**, not the source of synthetic customer behaviour.

## What is and isn't covered

Covered: scoring for the three audiences, subscription copy and £7/daily settings, prospect qualification, suppression behaviour, draft preparation, offline synthetic message/response logging, log exporting, CRM isolation, mocked discovery pipeline, API configuration/authentication, and regression tests.

Not covered end-to-end with live services: Treg social API response schemas, Tavily search results, HelloMinds account authorization and replies, SurrealDB network writes, actual outreach channels or compliance approval, live subscriptions, Stripe payments, and automated daily delivery. Unit and mock integration tests cannot prove those services work in production.

**Never count synthetic responses as actual lead replies, sales or hackathon revenue.**
