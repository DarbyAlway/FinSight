import { fetchEventSource } from '@microsoft/fetch-event-source';

export interface StreamHandlers {
  onStage: (stage: string, detail: string) => void;
  onAnswer: (markdown: string) => void;
  onError: (message: string) => void;
}

/**
 * Open the SSE turn stream for a chat. The backend sends zero or more `stage`
 * events, then exactly one terminal `answer` or `error`, then closes. We abort
 * after the terminal event so fetch-event-source does not auto-reconnect.
 */
export async function sendMessage(
  chatId: string,
  content: string,
  h: StreamHandlers,
): Promise<void> {
  const ctrl = new AbortController();
  try {
    await fetchEventSource(`/chats/${chatId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
      signal: ctrl.signal,
      openWhenHidden: true,
      onmessage(ev) {
        if (!ev.event || ev.event === 'message') return;
        const data = ev.data ? JSON.parse(ev.data) : {};
        if (ev.event === 'stage') {
          h.onStage(data.stage ?? '', data.detail ?? '');
        } else if (ev.event === 'answer') {
          h.onAnswer(data.markdown ?? '');
          ctrl.abort();
        } else if (ev.event === 'error') {
          h.onError(data.message ?? 'Something went wrong');
          ctrl.abort();
        }
      },
      onclose() {
        ctrl.abort(); // server closed the stream — do not retry
      },
      onerror(err) {
        throw err; // stop retrying; surfaces as a rejected promise
      },
    });
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return; // clean terminal close
    throw err;
  }
}
