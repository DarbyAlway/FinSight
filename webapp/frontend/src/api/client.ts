import type { Chat, ChatDetail } from '../types';

export async function listChats(): Promise<Chat[]> {
  const r = await fetch('/chats');
  if (!r.ok) throw new Error(`listChats failed: ${r.status}`);
  return r.json();
}

export async function createChat(title = 'New chat'): Promise<string> {
  const r = await fetch('/chats', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error(`createChat failed: ${r.status}`);
  return (await r.json()).id as string;
}

export async function getChat(id: string): Promise<ChatDetail> {
  const r = await fetch(`/chats/${id}`);
  if (!r.ok) throw new Error(`getChat failed: ${r.status}`);
  return r.json();
}

export async function deleteChat(id: string): Promise<void> {
  const r = await fetch(`/chats/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`deleteChat failed: ${r.status}`);
}
