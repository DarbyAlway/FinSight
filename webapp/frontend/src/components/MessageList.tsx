import type { Message } from '../types';
import MessageBubble from './MessageBubble';

export default function MessageList({ messages }: { messages: Message[] }) {
  return (
    <div className="flex flex-col gap-3 p-4">
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} />
      ))}
    </div>
  );
}
