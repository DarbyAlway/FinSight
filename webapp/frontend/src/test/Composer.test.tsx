import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import Composer from '../components/Composer';

test('Enter sends trimmed text; Shift+Enter does not send', async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();
  render(<Composer disabled={false} onSend={onSend} />);
  const box = screen.getByPlaceholderText('Ask about a stock…');

  await user.type(box, 'AAPL revenue?');
  await user.keyboard('{Shift>}{Enter}{/Shift}');
  expect(onSend).not.toHaveBeenCalled();

  await user.keyboard('{Enter}');
  expect(onSend).toHaveBeenCalledWith('AAPL revenue?');
});

test('is disabled while streaming', () => {
  render(<Composer disabled={true} onSend={vi.fn()} />);
  expect(screen.getByRole('button')).toBeDisabled();
  expect(screen.getByPlaceholderText('Ask about a stock…')).toBeDisabled();
});
