import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

// App's effect calls loadChats() → client.listChats(); mock the API so the
// render is deterministic and no real fetch fires under jsdom.
vi.mock('../api/client', () => ({
  listChats: vi.fn(async () => []),
  getChat: vi.fn(async () => ({ id: 'x', title: '', created_at: '', updated_at: '', messages: [] })),
  createChat: vi.fn(async () => 'x'),
  deleteChat: vi.fn(async () => {}),
}));
vi.mock('../api/stream', () => ({ sendMessage: vi.fn() }));
// App gates on auth: mock the auth API so loadMe() resolves to a logged-in user.
const _u = { id: 'u1', email: 'u@x.com', is_owner: false, tokens_used: 0 };
vi.mock('../api/auth', () => ({
  getMe: vi.fn(async () => _u),
  login: vi.fn(async () => _u),
  register: vi.fn(async () => _u),
  logout: vi.fn(async () => {}),
}));

import App from '../App';
import { useAuthStore } from '../store/authStore';
import { useChatStore } from '../store/chatStore';

// jsdom does not evaluate Tailwind `md:` media queries, so this asserts the
// drawer toggle STATE (conditional rendering of the backdrop), not the CSS.
test('hamburger opens the sidebar drawer; backdrop closes it', async () => {
  const user = userEvent.setup();
  // Start already authenticated so the chat UI (not the loading/login screen) renders.
  useAuthStore.setState({ user: _u, status: 'authed' });
  render(<App />);

  // Closed initially → no backdrop.
  expect(screen.queryByLabelText('Close menu')).not.toBeInTheDocument();

  await user.click(screen.getByLabelText('Open menu'));
  expect(screen.getByLabelText('Close menu')).toBeInTheDocument();

  await user.click(screen.getByLabelText('Close menu'));
  expect(screen.queryByLabelText('Close menu')).not.toBeInTheDocument();
});

test('composer is enabled and shows the new placeholder before any chat is selected', async () => {
  useAuthStore.setState({ user: _u, status: 'authed' });
  render(<App />);

  expect(await screen.findByText('Ask about a stock to start a new chat.')).toBeInTheDocument();
  expect(screen.getByPlaceholderText('Ask about a stock…')).not.toBeDisabled();
});

test('composer is disabled and shows "…" while a chat is being created (sending true)', async () => {
  useAuthStore.setState({ user: _u, status: 'authed' });
  render(<App />);

  await screen.findByText('Ask about a stock to start a new chat.');
  // Simulate the store mid-way through auto-creating a chat for the first message.
  act(() => {
    useChatStore.setState({ sending: true });
  });

  expect(await screen.findByPlaceholderText('Ask about a stock…')).toBeDisabled();
  expect(screen.getByText('…')).toBeInTheDocument();
});
