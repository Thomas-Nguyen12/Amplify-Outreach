
import { createMindsClient } from '@animocabrands/minds-client-lib';

const key = process.env.MINDS_BUILDER_API_KEY;

if (!key) {
  throw new Error('MINDS_BUILDER_API_KEY is not set');
}

const aliases = [
  'research_dcd828557db5531ba8ca09a4',
  'research_c9cd502106b393ddb025d25d',
  'research_d515233c05376f1e840ca84c',
  'research_9d0b6f73c4fb3c454f1e1472',
];

const client = createMindsClient({ builderApiKey: key });

for (const alias of aliases) {
  try {
    const history = await client.getHistory(alias, { limit: 50 });

    console.log(`\nConversation: ${alias}`);
    console.log(`Messages found: ${history.length}`);

    for (const message of history) {
      // Only inspect messages authored by the Mind.
      if (![0, 2].includes(message.senderType)) {
        continue;
      }

      const text = String(message.messageText || '');
      let status = 'unstructured';

      try {
        const parsed = JSON.parse(
          text
            .replace(/^```(?:json)?\s*/i, '')
            .replace(/\s*```$/, '')
        );

        status = parsed.status || 'JSON without status';
      } catch {
        // Do not treat unstructured replies as completed research.
      }

      console.log({
        senderType: message.senderType,
        status,
        fingerprintPresent: Boolean(message.fingerprint),
        textLength: text.length,
      });
	    console.log('Response preview:',text.slice(0,350).replace(/\s+/g, ' '));
    }
  } catch (error) {
    console.error(`Error for ${alias}: ${error.message}`);
  }
}
