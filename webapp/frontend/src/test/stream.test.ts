import { vi } from 'vitest';

// Mock the SSE library: invoke the caller's onmessage with fake frames.
vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: vi.fn(async (_url: string, opts: any) => {
    opts.onmessage({ event: 'stage', data: JSON.stringify({ stage: 'planning', detail: '' }) });
    opts.onmessage({ event: 'stage', data: JSON.stringify({ stage: 'fetching', detail: 'AAPL: financials' }) });
    opts.onmessage({ event: 'answer', data: JSON.stringify({ markdown: 'Revenue was 391,035M.' }) });
  }),
}));

import { fetchEventSource } from '@microsoft/fetch-event-source';
import { sendMessage } from '../api/stream';

test('sendMessage POSTs and routes stage/answer events to handlers', async () => {
  const stages: Array<[string, string]> = [];
  let answer = '';
  await sendMessage('chat-1', 'AAPL revenue?', {
    onStage: (s, d) => stages.push([s, d]),
    onAnswer: (md) => { answer = md; },
    onError: () => { throw new Error('should not error'); },
  });

  expect(stages).toEqual([['planning', ''], ['fetching', 'AAPL: financials']]);
  expect(answer).toBe('Revenue was 391,035M.');

  const [url, opts] = (fetchEventSource as any).mock.calls[0];
  expect(url).toBe('/chats/chat-1/messages');
  expect(opts.method).toBe('POST');
  expect(JSON.parse(opts.body)).toEqual({ content: 'AAPL revenue?' });
});

test('sendMessage routes an error event to onError', async () => {
  (fetchEventSource as any).mockImplementationOnce(async (_url: string, opts: any) => {
    opts.onmessage({ event: 'error', data: JSON.stringify({ message: 'EDGAR timed out' }) });
  });
  let err = '';
  await sendMessage('c', 'x', { onStage: () => {}, onAnswer: () => {}, onError: (m) => { err = m; } });
  expect(err).toBe('EDGAR timed out');
});
