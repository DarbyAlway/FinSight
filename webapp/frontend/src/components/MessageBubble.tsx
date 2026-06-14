import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../types';

export default function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  return (
    <div className={isUser ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm shadow-sm sm:max-w-2xl ${
          isUser
            ? 'bg-green-600 text-white'
            : 'border border-white/10 bg-neutral-800/80 text-neutral-100'
        }`}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : (
          <div className="markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
