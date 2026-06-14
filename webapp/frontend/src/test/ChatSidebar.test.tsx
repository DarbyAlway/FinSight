import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import ChatSidebar from '../components/ChatSidebar';

test('lists chats and fires select / new / delete', async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  const onNew = vi.fn();
  const onDelete = vi.fn();
  render(
    <ChatSidebar
      chats={[{ id: 'a', title: 'Apple', updated_at: '' }]}
      currentChatId={null}
      onSelect={onSelect}
      onNew={onNew}
      onDelete={onDelete}
    />,
  );

  await user.click(screen.getByText('Apple'));
  expect(onSelect).toHaveBeenCalledWith('a');

  await user.click(screen.getByText('+ New chat'));
  expect(onNew).toHaveBeenCalled();

  await user.click(screen.getByLabelText('Delete Apple'));
  expect(onDelete).toHaveBeenCalledWith('a');
});
