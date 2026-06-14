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
    <aside className="flex h-full w-full flex-col border-r border-white/10 bg-[#11141b]">
      <div className="flex items-center gap-2 px-4 py-4">
        <span className="inline-block h-3 w-3 rounded-sm bg-indigo-500" aria-hidden="true" />
        <span className="text-lg font-semibold tracking-tight">FinSight</span>
      </div>
      <div className="px-3">
        <button
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500"
          onClick={onNew}
        >
          + New chat
        </button>
      </div>
      <ul className="mt-3 flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {chats.map((c) => {
          const active = c.id === currentChatId;
          return (
            <li
              key={c.id}
              className={`group flex items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors ${
                active ? 'bg-white/10 text-white' : 'text-neutral-300 hover:bg-white/5'
              }`}
            >
              <button className="flex-1 truncate text-left" onClick={() => onSelect(c.id)}>
                {c.title}
              </button>
              <button
                aria-label={`Delete ${c.title}`}
                className="ml-2 text-neutral-500 opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
                onClick={() => onDelete(c.id)}
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
