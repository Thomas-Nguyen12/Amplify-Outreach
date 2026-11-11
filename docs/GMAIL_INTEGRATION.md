# Gmail API integration: local Mac setup and safe deployment

The project supports `OUTREACH_PROVIDER=gmail` in addition to the existing Resend adapter. The Google API integration has been **implemented and unit-tested with mocks**, not live-authorised in the supplied ZIP. No secrets are included. Real Gmail/SurrealDB tests require your own runtime, account, and consent records.

## 1. Install / merge the updated project

Back up the original project. Extract this ZIP to a new directory or merge its source files into the directory containing your local `.env` and `credentials/`. **Do not overwrite your private `.env` with `.env.example` and do not place OAuth secrets into the ZIP or GitHub.** Install:

```bash
python -m pip install -r requirements.txt
```

Your earlier `scripts/test_gmail.py` and successful Gmail OAuth test can remain in your local project. They are not included in this downloadable source ZIP.

## 2. Keep configuration off until ready

Add or update these entries in the project-root `.env` (replace placeholders with real values):

```dotenv
OUTREACH_PROVIDER=gmail
GMAIL_OAUTH_CLIENT_FILE=credentials/gmail_oauth.json
GMAIL_TOKEN_FILE=credentials/gmail_token.json
OUTREACH_FROM_EMAIL=your-dedicated-account@gmail.com
OUTREACH_REPLY_TO=your-dedicated-account@gmail.com
OUTREACH_SENDER_NAME=Social Trend Analytics
GMAIL_REPLY_POLL_ENABLED=false
OUTREACH_AUTOSEND_ENABLED=false
OUTREACH_MAX_PER_DAY=3
# Required for protected FastAPI outreach/inbox endpoints:
AGENT_API_KEY=generate_a_long_random_private_value
```

Existing SurrealDB settings and documented hackathon permission flags still apply. `OUTREACH_FROM_EMAIL` must be the actual authorised Gmail sender; sending is subject to Google's policies. **Do not enter a Gmail account as a sender for the Resend provider.**

## 3. Upgrade OAuth for reading replies

Your current `gmail_token.json` was created with `gmail.send` only. For reply monitoring, go to Google Cloud Console > Google Auth Platform > Data Access, add `gmail.readonly` if required by the consent configuration, and add your Gmail account as a Test user under Audience. The read-only permission is a **restricted scope**: external/public deployments may need additional Google verification/security review. Keep this a local private pilot. Read the actual permissions displayed before consenting.

Run **on your Mac with a browser**, using the exact same Google Cloud OAuth Desktop client JSON as in the earlier successful test:

```bash
python -m scripts.authorize_gmail --read-replies
```

This reopens a Google authorisation page and writes a replacement `credentials/gmail_token.json` containing permission for both sending and reading. No tokens should ever be pasted into chat, stored in source control, or included in a downloadable archive. The script writes it with private file permissions. If you only need to renew send permission, run `python -m scripts.authorize_gmail` without the read flag.

**Testing-mode OAuth refresh tokens can expire after about 7 days**; re-authorisation may be needed. The API service refreshes an unexpired refresh token but **never opens an OAuth browser**. For unattended deployment, use an appropriate Google OAuth publishing/verification process and a secure secret-delivery mechanism. Do not assume locally created token files are present on a new Daytona sandbox.

## 4. Verify the integrated service

Start the app with your existing runtime:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8006
```

Check with an authenticated request (`x-agent-key` required if `AGENT_API_KEY` is configured):

```bash
curl -s -H "x-agent-key: $AGENT_API_KEY" http://127.0.0.1:8006/gmail/status
curl -s -H "x-agent-key: $AGENT_API_KEY" http://127.0.0.1:8006/outreach/status
```

If your shell does not already have `AGENT_API_KEY` exported, use a secure environment loading method (avoid exposing it via shared terminal history). `/gmail/status` reports client/token file presence and granted scopes without exposing tokens. `/outreach/status` will still report `ready=false` until all independent legal, hackathon, recipient, and infrastructure flags are enabled.

Existing registration/dispatch endpoints remain:

- `POST /outreach/contacts` — **only after independent, auditable affirmative opt-in**, not publicly listed contact information.
- `POST /outreach/dispatch?limit=1` — attempts eligible already-consented drafts only when *all* gates pass; uses Gmail if selected.
- `GET /outreach/attempts` — durable attempts and Gmail message IDs.
- `POST /outreach/optout` — immediately suppress a contact.
- `POST /gmail/replies/poll?limit=50` — manually trigger Gmail inbox reconciliation when enabled.

A successful Gmail `provider_id` indicates **API acceptance only**, not actual delivery or a customer reply. There is **no automatic retry** after a claimed send has an uncertain result because Gmail does not expose the Resend idempotency-key mechanism. Inspect the Gmail Sent folder and persistence records before resolving an uncertain send.

**This system is strictly permission-based**. Do not switch the permission flags to `true` without actual independent authority, approved channel use, and opt-in evidence. Google prohibits unsolicited commercial bulk/spam messages. Hackathon organiser approval is a separate requirement from Gmail policy.

## 5. Opt-outs and inbox reconciliation

After authorising read permission and checking `/gmail/status`, enable:

```dotenv
GMAIL_REPLY_POLL_ENABLED=true
```

Restart the API (settings are cached per process). Reconcile on demand:

```bash
python -m scripts.poll_gmail_replies --limit 50
```

Or send a protected `POST` request to `/gmail/replies/poll?limit=50`. A scheduler you control can run the one-shot script regularly **only when the credentials and persistent SurrealDB settings are available**. Polling does not send messages.

Safeguards:

- Reads at most 100 of the newest inbox messages per run; a high-volume inbox needs pagination/high-water-mark enhancements.
- Only matches received mail to a previously accepted **outgoing Gmail attempt**, from the exact registered recipient, with a post-send timestamp and matching `In-Reply-To` / `References` header.
- Explicit requests such as `STOP` or `Please unsubscribe` immediately create a durable suppression before marking the reply processed.
- Other replies are recorded as `needs_review` for a human to check in Gmail; there is no automatic sales classification or reply generation.
- Does **not** automatically suppress replies sent as new threads, from a different address, or without correlation headers. The inbox **must still be monitored by a human**, especially for opt-outs not caught by this conservative algorithm. Do not treat an empty poll as proof that there are no replies.
- No message body is persisted in the reply event record. Events are deduplicated using Gmail message ID.
- `/outreach/replies` remains available for authenticated, independently verified manual reply logging.

For full autonomy, add safe ongoing scheduling, pagination and an operational review dashboard. These are **not** claimed as implemented. Contact lists, GDPR obligations, retention, marketing-law checks and Gmail acceptable-use requirements remain your responsibility.

## 6. Run tests

```bash
python -m pytest -q
```

The bundled suite passes locally without sending real emails: **95 passed, 2 skipped**. Skips concern optional credential-gated integrations. The only live Gmail confirmation so far is **your own earlier standalone successful test** on your Mac; this updated agent has not been connected to your private Gmail account in this environment.
