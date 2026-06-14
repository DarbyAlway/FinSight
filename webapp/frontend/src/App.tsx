import { useEffect } from 'react';
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

  useEffect(() => {
    loadChats();
  }, [loadChats]);

  return (
    <div className="flex h-screen">
      <ChatSidebar
        chats={chats}
        currentChatId={currentChatId}
        onSelect={selectChat}
        onNew={newChat}
        onDelete={deleteChat}
      />
      <main className="flex flex-1 flex-col">
        <div className="flex-1 overflow-y-auto">
          {currentChatId ? (
            <MessageList messages={messages} />
          ) : (
            <div className="p-8 text-center text-gray-400">Select or start a chat.</div>
          )}
        </div>
        {error && <div className="px-4 py-2 text-sm text-red-600">{error}</div>}
        <StageIndicator stage={stage} />
        <Composer disabled={status === 'streaming' || !currentChatId} onSend={send} />
      </main>
    </div>
  );
}
