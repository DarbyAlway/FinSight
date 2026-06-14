import { render, screen } from '@testing-library/react';
import StageIndicator from '../components/StageIndicator';

test('shows a friendly label and detail while a stage is set', () => {
  render(<StageIndicator stage={{ stage: 'fetching', detail: 'AAPL: financials' }} />);
  expect(screen.getByRole('status')).toHaveTextContent('Fetching data… (AAPL: financials)');
});

test('renders nothing when stage is null', () => {
  const { container } = render(<StageIndicator stage={null} />);
  expect(container).toBeEmptyDOMElement();
});
