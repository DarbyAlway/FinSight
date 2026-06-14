import { useState } from 'react';

export default function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState('');

  const submit = () => {
    const t = text.trim();
    if (!t || disabled) return;
    onSend(t);
    setText('');
  };

  return (
    <div className="border-t border-white/10 p-3">
      <div className="flex max-w-3xl items-end gap-2">
        <textarea
          className="max-h-40 flex-1 resize-none rounded-xl border border-white/10 bg-neutral-900 px-4 py-2.5 text-sm text-neutral-100 placeholder-neutral-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
          rows={1}
          value={text}
          placeholder="Ask about a stock…"
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={disabled}
          onClick={submit}
        >
          {disabled ? '…' : 'Send'}
        </button>
      </div>
    </div>
  );
}
