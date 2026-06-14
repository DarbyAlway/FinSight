import type { Message } from '../types';
import MessageBubble from './MessageBubble';

export default function MessageList({ messages }: { messages: Message[] }) {
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} />
      ))}
    </div>
  );
}
