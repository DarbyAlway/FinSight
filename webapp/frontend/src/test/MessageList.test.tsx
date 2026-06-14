import { render, screen } from '@testing-library/react';
import MessageList from '../components/MessageList';

test('renders an assistant markdown table and link as real DOM', () => {
  const md = [
    '| Metric | FY2024 |',
    '| --- | --- |',
    '| Revenue | 391,035M |',
    '',
    '[Source](https://www.sec.gov)',
  ].join('\n');
  render(<MessageList messages={[{ role: 'assistant', content: md }]} />);

  expect(screen.getByRole('table')).toBeInTheDocument();
  expect(screen.getByRole('cell', { name: '391,035M' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Source' })).toHaveAttribute('href', 'https://www.sec.gov');
});

test('renders a user message as plain text', () => {
  render(<MessageList messages={[{ role: 'user', content: 'AAPL revenue?' }]} />);
  expect(screen.getByText('AAPL revenue?')).toBeInTheDocument();
});
