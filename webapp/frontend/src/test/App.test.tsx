import { render, screen } from '@testing-library/react';
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

import App from '../App';

// jsdom does not evaluate Tailwind `md:` media queries, so this asserts the
// drawer toggle STATE (conditional rendering of the backdrop), not the CSS.
test('hamburger opens the sidebar drawer; backdrop closes it', async () => {
  const user = userEvent.setup();
  render(<App />);

  // Closed initially → no backdrop.
  expect(screen.queryByLabelText('Close menu')).not.toBeInTheDocument();

  await user.click(screen.getByLabelText('Open menu'));
  expect(screen.getByLabelText('Close menu')).toBeInTheDocument();

  await user.click(screen.getByLabelText('Close menu'));
  expect(screen.queryByLabelText('Close menu')).not.toBeInTheDocument();
});
