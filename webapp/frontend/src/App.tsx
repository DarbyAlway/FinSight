import { useEffect, useState } from 'react';
import { useChatStore } from './store/chatStore';
import ChatSidebar from './components/ChatSidebar';
import MessageList from './components/MessageList';
import StageIndicator from './components/StageIndicator';
import Composer from './components/Composer';

export default function App() {
  const chats = useChatStore((s) => s.chats);
  const currentChatId = useChatStore((s) => s.currentChatId);
  const messages = useChatStore((s) => s.messages);
  const status = useChatStore((s) => s.status);
  const stage = useChatStore((s) => s.stage);
  const error = useChatStore((s) => s.error);
  const loadChats = useChatStore((s) => s.loadChats);
  const selectChat = useChatStore((s) => s.selectChat);
  const newChat = useChatStore((s) => s.newChat);
  const deleteChat = useChatStore((s) => s.deleteChat);
  const send = useChatStore((s) => s.send);

  // UI-only: whether the off-canvas sidebar drawer is open on mobile.
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    loadChats();
  }, [loadChats]);

  const handleSelect = (id: string) => {
    selectChat(id);
    setSidebarOpen(false);
  };
  const handleNew = () => {
    newChat();
    setSidebarOpen(false);
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[#0b0d12] text-neutral-100">
      {/* Mobile backdrop (only rendered while the drawer is open) */}
      {sidebarOpen && (
        <button
          aria-label="Close menu"
          className="fixed inset-0 z-20 bg-black/60 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar: static column on desktop, off-canvas drawer on mobile */}
      <div
        className={`fixed inset-y-0 left-0 z-30 w-72 transform transition-transform duration-200 md:static md:z-auto md:w-64 md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <ChatSidebar
          chats={chats}
          currentChatId={currentChatId}
          onSelect={handleSelect}
          onNew={handleNew}
          onDelete={deleteChat}
        />
      </div>

      <main className="flex min-w-0 flex-1 flex-col">
        {/* Mobile header with the menu toggle */}
        <header className="flex items-center gap-3 border-b border-white/10 px-4 py-3 md:hidden">
          <button
            aria-label="Open menu"
            className="rounded-lg p-1.5 text-neutral-300 hover:bg-white/10"
            onClick={() => setSidebarOpen(true)}
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <span className="font-semibold tracking-tight">FinSight</span>
        </header>

        <div className="flex-1 overflow-y-auto">
          {currentChatId ? (
            <MessageList messages={messages} />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-center text-neutral-500">
              Select or start a chat.
            </div>
          )}
        </div>

        {error && (
          <div className="mx-auto mb-2 w-full max-w-3xl rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </div>
        )}
        <StageIndicator stage={stage} />
        <Composer disabled={status === 'streaming' || !currentChatId} onSend={send} />
      </main>
    </div>
  );
}
