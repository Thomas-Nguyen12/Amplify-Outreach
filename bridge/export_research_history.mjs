
import { createMindsClient } from '@animocabrands/minds-client-lib';

const alias = process.argv[2];
const key = process.env.MINDS_BUILDER_API_KEY;

if (!key) {
  throw new Error('MINDS_BUILDER_API_KEY is missing');
}

if (!/^[a-zA-Z0-9_-]{1,100}$/.test(alias || '')) {
  throw new Error('Invalid research conversation alias');
}

const client = createMindsClient({
  builderApiKey: key,
});

// GET history only. Do not ensure/create a conversation
// and do not send any new messages.
const history = await client.getHistory(alias, {
  limit: 100,
});

// Return Mind-authored messages only.
// Keep reports on stdout for the Python recovery program;
// do not write them to a file.
const messages = history
  .filter(message => [0, 2].includes(message.senderType))
  .map(message => ({
    fingerprint: message.fingerprint,
    createdAt: message.createdAt || null,
    reply: message.messageText || '',
  }));

process.stdout.write(JSON.stringify({ alias, messages }));
