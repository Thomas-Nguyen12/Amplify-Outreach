-- Run ONLY against the intended SurrealDB namespace and database.
-- The Python code uses deterministic record IDs and SurrealDB CREATE for locks.
DEFINE TABLE IF NOT EXISTS contact_routes SCHEMALESS;
DEFINE TABLE IF NOT EXISTS outreach_send_claims SCHEMALESS;
DEFINE TABLE IF NOT EXISTS outreach_daily_slots SCHEMALESS;
DEFINE TABLE IF NOT EXISTS outreach_send_attempts SCHEMALESS;
DEFINE TABLE IF NOT EXISTS outreach_reply_events SCHEMALESS;
-- Existing tables also required: prospects, research_briefs,
-- outreach_drafts, suppression.
