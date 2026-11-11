
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  findSubmittedPrompt,
  waitForPromptFingerprint,
} from './research.mjs';

test('new conversation recovers the actual prompt fingerprint', async () => {
  const prompt = 'Research Example Coffee Shop';
  let calls = 0;

  const fakeClient = {
    async getHistory(alias) {
      assert.equal(alias, 'research_example');
      calls++;

      if (calls === 1) {
        return [];
      }

      return [
        {
          senderType: 0,
          messageText: '{"status":"completed"}',
          fingerprint: 'mind-reply-fingerprint',
        },
        {
          senderType: 1,
          messageText: prompt,
          fingerprint: 'submitted-prompt-fingerprint',
        },
      ];
    },
  };

  const fingerprint = await waitForPromptFingerprint(
    fakeClient,
    'research_example',
    prompt
  );

  assert.equal(fingerprint, 'submitted-prompt-fingerprint');
  assert.equal(calls, 2);
});

test('existing research prompt is recognised', () => {
  const prompt = 'Research Example Coffee Shop';

  const history = [
    {
      senderType: 1,
      messageText: prompt,
      fingerprint: 'original-prompt-fingerprint',
    },
  ];

  const match = findSubmittedPrompt(history, prompt);

  assert.equal(match?.fingerprint, 'original-prompt-fingerprint');
});

test('unrelated research prompts are rejected', () => {
  const history = [
    {
      senderType: 1,
      messageText: 'Research a different business',
      fingerprint: 'other-fingerprint',
    },
  ];

  const match = findSubmittedPrompt(
    history,
    'Research Example Coffee Shop'
  );

  assert.equal(match, undefined);
});

test('AI replies are not mistaken for submitted prompts', () => {
  const prompt = 'Research Example Coffee Shop';

  const history = [
    {
      senderType: 0,
      messageText: prompt,
      fingerprint: 'mind-fingerprint',
    },
  ];

  assert.equal(findSubmittedPrompt(history, prompt), undefined);
});
