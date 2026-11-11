# HelloMinds durable research recovery — local and Daytona

## What changed

- `bridge/research.mjs` has two modes, **start** and **poll**. **Poll does not call `sendMessage`.**
- Starts produce a short bounded response. A timeout or an acknowledgement leaves the job **pending** rather than falsely completed.
- SurrealDB `research_briefs` stores `status`, `alias`, `after_fingerprint`, `reply`, and the prospect identity. The existing table is reused; no new SurrealDB schema is required.
- A later Daytona sandbox can check the pending record, resume its conversation history and store a final structured report.
- Existing history-only jobs created before this change generally have **no saved fingerprint**. The app will not re-send them automatically; import a finished report after manually checking history.
- Final reports are marked completed, but source citations **are not automatically verified by the Mind's assertion**. Outreach-specific findings are correlated against captured source text/URLs only. Unsupported or malformed citations are excluded from drafts.
- The customer acquisition workflow does **not** send messages. New customer-facing outreach drafts do not contain prices.

## Install and start

```sh
python -m pip install -r requirements.txt
cd bridge && npm install && cd ..
python -m uvicorn app.main:app --host 127.0.0.1 --port 8005
```

Keep `.env` private; configure `MINDS_ENABLED=true`, `MINDS_BUILDER_API_KEY`, `MINDS_RESEARCH_MIND_ID`, `SURREAL_ENABLED=true` and your existing SurrealDB settings. Do **not** point this at `integration_test` when running against real prospect records.

## Recover from a research timeout

Open http://127.0.0.1:8005/docs and call:

1. `GET /research/persistent/pending` to see aliases of pending conversations.
2. `POST /research/persistent/reconcile?limit=2` to **poll** at most two pending jobs. No new research prompt is sent by this endpoint.
3. `GET /persistent/research` to inspect stored statuses and final JSON.
4. `GET /persistent/drafts` to inspect drafts if any prospect genuinely qualifies.

A one-shot Daytona job can run:

```sh
python -m scripts.reconcile_research --limit 2
```

Schedule the one-shot command hourly using your existing authorised scheduler. This repository's Daytona smoke runner does not itself create a live hourly scheduler. Run bounded batches so a transient HelloMinds delay does not exhaust sandbox time or quotas.

## Reconcile a previously finished conversation (such as CF655841)

Old requests may not have a saved `after_fingerprint` and therefore cannot be safely polled without rediscovering the exact history state. **Do not repeatedly re-send the original prompt.** After inspecting HelloMinds history, the full JSON report can be imported explicitly:

```sh
curl -sS -X POST 'http://127.0.0.1:8005/research/persistent/import' \
  -H 'Content-Type: application/json' \
  --data-binary @examples/dpl_seller_academy_import.json
```

If your server requires `AGENT_API_KEY`, add the application's configured `x-agent-key` header privately. The example file is a **normalized reconstruction** of the supplied DPL report: malformed Markdown-wrapped URLs were rewritten to plain URLs and the core findings were retained. Review and correct it against the original report before import. It is NOT independent source verification. Do not use it to claim that DPL has a content-marketing problem.

Expected for DPL: valid `status=completed`, zero accepted outreach-specific evidence, unqualified, no draft and no outbound message.

## Limitations and guardrails

- An acknowledgement, pending JSON, malformed JSON, or timeout must **not** generate a draft.
- Only pre-captured public source text is eligible for verbatim quote matching; cited outside websites from the Mind are not independently fetched or verified by this application.
- The bridge is designed for the installed `@animocabrands/minds-client-lib`. Its actual live polling semantics still require a credentialed integration test with your account; no live Minds call was made while building this release.
- If the bridge process dies *during* the initial `sendMessage` operation, the app may not have saved a marker yet. Treat ambiguous delivery as a manual reconciliation case rather than automatically resending.
- Concurrent writers and quota accounting should be hardened with atomic leases and a shared quota counter before deploying a production scheduler.
- Suppression is checked before polling, research results alone cannot infer buying intent, and all drafts are unsent and require human/channel approval.
