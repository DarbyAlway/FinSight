import { afterEach, vi } from 'vitest';
import { listChats, createChat, getChat, deleteChat } from '../api/client';

afterEach(() => vi.restoreAllMocks());

function mockFetch(body: unknown, ok = true, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok, status, json: async () => body,
  } as Response);
}

test('listChats GETs /chats and returns the array', async () => {
  const f = mockFetch([{ id: 'a', title: 't', updated_at: 'x' }]);
  const chats = await listChats();
  expect(f).toHaveBeenCalledWith('/chats');
  expect(chats).toEqual([{ id: 'a', title: 't', updated_at: 'x' }]);
});

test('createChat POSTs a title and returns the new id', async () => {
  const f = mockFetch({ id: 'new-id' });
  const id = await createChat('Apple');
  expect(id).toBe('new-id');
  const [url, opts] = f.mock.calls[0];
  expect(url).toBe('/chats');
  expect(opts?.method).toBe('POST');
  expect(JSON.parse(opts?.body as string)).toEqual({ title: 'Apple' });
});

test('getChat GETs /chats/{id}', async () => {
  mockFetch({ id: 'a', title: 't', created_at: '', updated_at: '', messages: [] });
  const chat = await getChat('a');
  expect(chat.messages).toEqual([]);
});

test('deleteChat DELETEs and throws on non-ok', async () => {
  mockFetch({}, false, 500);
  await expect(deleteChat('a')).rejects.toThrow();
});
