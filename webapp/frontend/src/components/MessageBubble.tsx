import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../types';

export default function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  return (
    <div className={isUser ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={`max-w-[85%] overflow-hidden break-words rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
          isUser
            ? 'bg-green-600 text-white sm:max-w-2xl'
            : 'border border-white/10 bg-[#262b36] text-neutral-100 sm:max-w-3xl'
        }`}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : (
          <div className="markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // Wrap wide tables so they scroll horizontally inside the
                // bubble instead of overflowing past its border.
                table({ node, ...props }) {
                  return (
                    <div className="md-table-wrap">
                      <table {...props} />
                    </div>
                  );
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
