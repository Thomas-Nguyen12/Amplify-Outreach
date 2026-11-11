import { createMindsClient } from '@animocabrands/minds-client-lib';
async function main() {
  const input = JSON.parse(process.argv[2] || '{}');
  const key = process.env.MINDS_BUILDER_API_KEY, mindId = process.env.MINDS_RESEARCH_MIND_ID;
  if (!key || !mindId) throw new Error('Mind key and ID are required');
  const alias = input.alias;
  if (!/^[a-zA-Z0-9_-]{1,100}$/.test(alias || '')) throw new Error('Invalid conversation alias');
  if (!['start','poll'].includes(input.mode || 'start')) throw new Error('Invalid bridge mode');
  const client = createMindsClient({ builderApiKey: key });
  await client.ensureConversation(alias, mindId);
  let fingerprint;
  if ((input.mode || 'start') === 'start') {
    if (!input.prompt) throw new Error('Missing research prompt');
    fingerprint = await client.getLatestHistoryFingerprint(alias);
    await client.sendMessage({ alias, messageText: input.prompt });
  } else {
    if (!Object.prototype.hasOwnProperty.call(input, 'after_fingerprint')) throw new Error('No saved history marker; cannot resume');
    fingerprint = input.after_fingerprint;
  }
  const timeoutMs = input.mode === 'poll' ? Number(process.env.MINDS_POLL_WAIT_MS || 12000) : 3000;
  let outcome;
  try {
    outcome = await client.waitForReply({ alias, timeoutMs, afterFingerprint: fingerprint,
      sentMessageText: input.prompt || '' });
  } catch (err) {
    // Do NOT re-send the research prompt on a timeout: the Mind may still be working.
    if (!/timed?\s*out|timeout/i.test(String(err?.message || err))) throw err;
    outcome = {timedOut:true};
  }
  const reply = outcome.reply?.messageText || '';
  let parsed;
  try { parsed = JSON.parse(reply.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')); }
  catch { parsed = null; }
  const pending = !!outcome.timedOut || !parsed || parsed.status !== 'completed';
  // Skip acknowledgements, malformed reports and pending JSON on the next poll.
  const nextFingerprint = pending && reply ? await client.getLatestHistoryFingerprint(alias) : fingerprint;
  process.stdout.write(JSON.stringify({alias, mind_id: mindId, after_fingerprint: nextFingerprint,
    reply, pending}));
}
main().catch(e => { process.stderr.write(String(e?.stack || e) + '\n'); process.exitCode = 1; });
