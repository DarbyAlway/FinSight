import { beforeEach, vi } from 'vitest';

vi.mock('../api/client', () => ({
  listChats: vi.fn(async () => [{ id: 'c1', title: 't', updated_at: '' }]),
  getChat: vi.fn(async () => ({ id: 'c1', title: 't', created_at: '', updated_at: '', messages: [] })),
  createChat: vi.fn(async () => 'c1'),
  deleteChat: vi.fn(async () => {}),
}));
vi.mock('../api/stream', () => ({
  sendMessage: vi.fn(async (_id: string, _c: string, h: any) => {
    h.onStage('planning', '');
    h.onAnswer('Revenue was 391,035M.');
  }),
}));

import { useChatStore } from '../store/chatStore';
import { sendMessage } from '../api/stream';

beforeEach(() => {
  useChatStore.setState({
    chats: [], currentChatId: null, messages: [], status: 'idle', stage: null, error: null,
  });
  vi.clearAllMocks();
});

test('loadChats fills the chat list', async () => {
  await useChatStore.getState().loadChats();
  expect(useChatStore.getState().chats).toHaveLength(1);
});

test('send appends the user message then the assistant answer, status returns to idle', async () => {
  useChatStore.setState({ currentChatId: 'c1' });
  await useChatStore.getState().send('AAPL revenue?');
  const s = useChatStore.getState();
  expect(s.messages.map((m) => m.role)).toEqual(['user', 'assistant']);
  expect(s.messages[1].content).toContain('391,035M');
  expect(s.status).toBe('idle');
  expect(s.stage).toBeNull();
});

test('send sets error state and keeps the user message on an error event', async () => {
  (sendMessage as any).mockImplementationOnce(async (_i: string, _c: string, h: any) => h.onError('EDGAR timed out'));
  useChatStore.setState({ currentChatId: 'c1' });
  await useChatStore.getState().send('x');
  const s = useChatStore.getState();
  expect(s.status).toBe('error');
  expect(s.error).toContain('EDGAR timed out');
  expect(s.messages.map((m) => m.role)).toEqual(['user']);
});

test('send with no current chat creates one first, then sends to it', async () => {
  useChatStore.setState({ currentChatId: null });
  await useChatStore.getState().send('AAPL revenue?');
  const s = useChatStore.getState();
  expect(s.currentChatId).toBe('c1');
  expect(s.messages.map((m) => m.role)).toEqual(['user', 'assistant']);
  expect(s.status).toBe('idle');
});
