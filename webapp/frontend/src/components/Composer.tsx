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
    <div className="flex gap-2 border-t p-3">
      <textarea
        className="flex-1 resize-none rounded border px-3 py-2"
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
        className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
        disabled={disabled}
        onClick={submit}
      >
        {disabled ? '…' : 'Send'}
      </button>
    </div>
  );
}
