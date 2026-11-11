
import { createMindsClient } from '@animocabrands/minds-client-lib';
import { pathToFileURL } from 'node:url';
/**
 * Amplify — HelloMinds Research Bridge
 *
 * Modes:
 *   start: Start research, unless the same prompt already exists.
 *   poll:  Resume an existing research conversation.
 *
 * Safety:
 *   - Never intentionally submit duplicate research prompts.
 *   - Never resend a prompt after a timeout.
 *   - Use actual message fingerprints, not fabricated cursors.
 *   - Accept only structured completed reports.
 *   - Never send customer-facing messages.
 */

const sleep = (ms) =>
  new Promise((resolve) => setTimeout(resolve, ms));

function parseResearchReply(reply) {
  if (typeof reply !== 'string' || !reply.trim()) {
    return null;
  }

  let text = reply.trim();

  // Remove HelloMinds HTML formatting.
  text = text
    .replace(/^<pre(?:\s[^>]*)?>\s*/i, '')
    .replace(/\s*<\/pre>\s*$/i, '')
    .trim();

  // Remove Markdown code fences.
  text = text
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim();

  // Support HTML wrappers around Markdown.
  text = text
    .replace(/^<pre(?:\s[^>]*)?>\s*/i, '')
    .replace(/\s*<\/pre>\s*$/i, '')
    .trim();

  try {
    const parsed = JSON.parse(text);

    return (
      parsed !== null &&
      typeof parsed === 'object' &&
      !Array.isArray(parsed)
    )
      ? parsed
      : null;

  } catch {
    return null;
  }
}

function isCompletedReport(parsed) {
  return Boolean(
    parsed &&
    parsed.status === 'completed' &&
    typeof parsed.summary === 'string' &&
    parsed.summary.trim() &&
    Array.isArray(parsed.evidence) &&
    Array.isArray(parsed.limitations) &&
    Array.isArray(parsed.content_challenges)
  );
}

function isValidFingerprint(value) {
  return typeof value === 'string' && value.length > 0;
}

async function getHistory(client, alias) {
  return client.getHistory(alias, {
    limit: 100,
  });
}

export function findSubmittedPrompt(history, prompt) {
  return history.find(
    (message) =>
      message.senderType === 1 &&
      message.messageText === prompt &&
      isValidFingerprint(message.fingerprint)
  );
}

export async function waitForPromptFingerprint(
  client,
  alias,
  prompt
) {
  // Allow a short period for the submitted message
  // to appear in conversation history.
  for (let attempt = 0; attempt < 5; attempt++) {
    const history = await getHistory(client, alias);

    const match = findSubmittedPrompt(history, prompt);

    if (match) {
      return match.fingerprint;
    }

    if (attempt < 4) {
      await sleep(500);
    }
  }

  return undefined;
}

async function findReplyFingerprint(
  client,
  alias,
  replyText
) {
  const history = await getHistory(client, alias);

  const match = history.find(
    (message) =>
      [0, 2].includes(message.senderType) &&
      message.messageText === replyText &&
      isValidFingerprint(message.fingerprint)
  );

  return match?.fingerprint;
}

async function main() {
  const input = JSON.parse(process.argv[2] || '{}');

  const key = process.env.MINDS_BUILDER_API_KEY;
  const mindId = process.env.MINDS_RESEARCH_MIND_ID;

  if (!key || !mindId) {
    throw new Error(
      'MINDS_BUILDER_API_KEY and MINDS_RESEARCH_MIND_ID are required'
    );
  }

  const alias = input.alias;
  const mode = input.mode || 'start';

  if (!/^[a-zA-Z0-9_-]{1,100}$/.test(alias || '')) {
    throw new Error('Invalid conversation alias');
  }

  if (!['start', 'poll'].includes(mode)) {
    throw new Error('Invalid bridge mode');
  }

  if (mode === 'start' && !input.prompt) {
    throw new Error('Missing research prompt');
  }

  if (
    mode === 'poll' &&
    !isValidFingerprint(input.after_fingerprint)
  ) {
    throw new Error(
      'A valid saved fingerprint is required for polling'
    );
  }

  const client = createMindsClient({
    builderApiKey: key,
  });

  await client.ensureConversation(alias, mindId);

  let fingerprint;

  if (mode === 'start') {
    const history = await getHistory(client, alias);

    const existingPrompt = findSubmittedPrompt(
      history,
      input.prompt
    );

    if (existingPrompt) {
      // This exact prompt already exists.
      // Do not submit it again.
      fingerprint = existingPrompt.fingerprint;

    } else if (history.length > 0) {
      // Conversation exists but doesn't contain the
      // expected prompt. Don't risk sending a duplicate.
      throw new Error(
        'Conversation already contains history but the ' +
        'expected research prompt was not found. ' +
        'Manual reconciliation is required.'
      );

    } else {
      // Brand-new conversation.
      await client.sendMessage({
        alias,
        messageText: input.prompt,
      });

      // Capture the fingerprint of the submitted prompt
      // rather than the latest conversation message.
      fingerprint = await waitForPromptFingerprint(
        client,
        alias,
        input.prompt
      );
    }

  } else {
    // Poll mode never sends a message.
    fingerprint = input.after_fingerprint;
  }

  if (!isValidFingerprint(fingerprint)) {
    throw new Error(
      'Research prompt may have been submitted, but its ' +
      'history fingerprint could not be confirmed. ' +
      'Do not automatically resend. Recover by alias.'
    );
  }

  const timeoutMs = mode === 'poll'
    ? Number(process.env.MINDS_POLL_WAIT_MS || 12000)
    : 3000;

  let outcome;

  try {
    outcome = await client.waitForReply({
      alias,
      timeoutMs,
      afterFingerprint: fingerprint,
      sentMessageText: input.prompt || '',
    });

  } catch (error) {
    const message = String(error?.message || error);

    // A timeout does not mean the research failed.
    // The Mind may still be processing.
    if (!/timed?\s*out|timeout/i.test(message)) {
      throw error;
    }

    outcome = {
      timedOut: true,
    };
  }

  const reply = outcome?.reply?.messageText || '';

  const parsed = parseResearchReply(reply);

  const completed = isCompletedReport(parsed);

  const pending = (
    Boolean(outcome?.timedOut) ||
    !completed
  );

  let nextFingerprint = fingerprint;

  if (pending && reply) {
    // Advance past an acknowledgement or incomplete reply,
    // but only when its exact fingerprint is known.
    const replyFingerprint =
      (
        isValidFingerprint(outcome?.reply?.fingerprint)
          ? outcome.reply.fingerprint
          : await findReplyFingerprint(
              client,
              alias,
              reply
            )
      );

    if (isValidFingerprint(replyFingerprint)) {
      nextFingerprint = replyFingerprint;
    }
  }

  process.stdout.write(
    JSON.stringify({
      alias,
      mind_id: mindId,
      after_fingerprint: nextFingerprint,
      reply,
      pending,
    })
  );
}

if (
  process.argv[1] &&
  pathToFileURL(process.argv[1]).href === import.meta.url
) {
  main().catch((error) => {
    process.stderr.write(String(error?.stack || error) + '\n');
    process.exitCode = 1;
  });
}

