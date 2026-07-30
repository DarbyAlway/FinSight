import { create } from 'zustand';
import type { Chat, Message, StageInfo, StreamStatus } from '../types';
import * as client from '../api/client';
import { sendMessage } from '../api/stream';

interface ChatState {
  chats: Chat[];
  currentChatId: string | null;
  messages: Message[];
  status: StreamStatus;
  stage: StageInfo | null;
  error: string | null;
  loadChats: () => Promise<void>;
  selectChat: (id: string) => Promise<void>;
  newChat: () => Promise<void>;
  deleteChat: (id: string) => Promise<void>;
  send: (content: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
  chats: [],
  currentChatId: null,
  messages: [],
  status: 'idle',
  stage: null,
  error: null,

  loadChats: async () => {
    set({ chats: await client.listChats() });
  },

  selectChat: async (id) => {
    const chat = await client.getChat(id);
    set({ currentChatId: id, messages: chat.messages, status: 'idle', stage: null, error: null });
  },

  newChat: async () => {
    const id = await client.createChat();
    await get().loadChats();
    set({ currentChatId: id, messages: [], status: 'idle', stage: null, error: null });
  },

  deleteChat: async (id) => {
    await client.deleteChat(id);
    const wasCurrent = get().currentChatId === id;
    await get().loadChats();
    if (wasCurrent) set({ currentChatId: null, messages: [] });
  },

  send: async (content) => {
    if (!get().currentChatId) {
      try {
        await get().newChat();
      } catch (err) {
        set({ error: err instanceof Error ? err.message : String(err), status: 'error', stage: null });
        return;
      }
    }
    const id = get().currentChatId;
    if (!id) return;
    set((s) => ({
      messages: [...s.messages, { role: 'user', content }],
      status: 'streaming',
      stage: null,
      error: null,
    }));
    try {
      await sendMessage(id, content, {
        onStage: (stage, detail) => set({ stage: { stage, detail } }),
        onAnswer: (markdown) =>
          set((s) => ({
            messages: [...s.messages, { role: 'assistant', content: markdown }],
            status: 'idle',
            stage: null,
          })),
        onError: (message) => set({ error: message, status: 'error', stage: null }),
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err), status: 'error', stage: null });
    }
    // Refresh sidebar ordering after the turn (best-effort).
    get().loadChats().catch(() => {});
  },
}));
