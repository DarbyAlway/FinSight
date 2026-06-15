import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import AuthScreen from '../components/AuthScreen';

test('submits login credentials', async () => {
  const user = userEvent.setup();
  const onLogin = vi.fn(async () => {});
  render(<AuthScreen onLogin={onLogin} onRegister={vi.fn()} />);
  await user.type(screen.getByPlaceholderText('Email'), 'u@x.com');
  await user.type(screen.getByPlaceholderText('Password'), 'pw12345');
  await user.click(screen.getByRole('button', { name: /log in/i }));
  expect(onLogin).toHaveBeenCalledWith('u@x.com', 'pw12345');
});

test('shows an error when the action rejects', async () => {
  const user = userEvent.setup();
  render(<AuthScreen onLogin={vi.fn(async () => { throw new Error('401'); })} onRegister={vi.fn()} />);
  await user.type(screen.getByPlaceholderText('Email'), 'u@x.com');
  await user.type(screen.getByPlaceholderText('Password'), 'bad');
  await user.click(screen.getByRole('button', { name: /log in/i }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
});
