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
  sending: boolean;
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
  sending: false,

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
    // If a send is already running, ignore this call.
    // Without this, hitting Enter twice fast (before a chat exists) could create two chats at once.
    if (get().sending) return;
    // Mark "sending" true right away, before any await, so the guard above works immediately.
    set({ sending: true });
    try {
      if (!get().currentChatId) {
        // No chat is selected yet (e.g. the user typed on the root screen), so create one first.
        // This lets the user send a message directly without clicking "New chat" first.
        try {
          await get().newChat();
        } catch (err) {
          set({ error: err instanceof Error ? err.message : String(err), status: 'error', stage: null });
          return;
        }
      }
      const id = get().currentChatId;
      // newChat() should always set an id, so this should not happen in practice.
      // Kept as a cheap safety check in case it ever resolves without doing so.
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
    } finally {
      // Always clear the flag, no matter which path above we exited through.
      set({ sending: false });
    }
  },
}));
