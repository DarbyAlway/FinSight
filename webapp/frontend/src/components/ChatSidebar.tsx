import type { Chat } from '../types';

export default function ChatSidebar({
  chats,
  currentChatId,
  onSelect,
  onNew,
  onDelete,
}: {
  chats: Chat[];
  currentChatId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className="flex w-64 flex-col border-r bg-gray-50">
      <button className="m-2 rounded bg-blue-600 px-3 py-2 text-white" onClick={onNew}>
        + New chat
      </button>
      <ul className="flex-1 overflow-y-auto">
        {chats.map((c) => (
          <li
            key={c.id}
            className={`flex items-center justify-between px-3 py-2 ${
              c.id === currentChatId ? 'bg-blue-100' : ''
            }`}
          >
            <button className="flex-1 truncate text-left" onClick={() => onSelect(c.id)}>
              {c.title}
            </button>
            <button
              aria-label={`Delete ${c.title}`}
              className="ml-2 text-gray-400 hover:text-red-600"
              onClick={() => onDelete(c.id)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
