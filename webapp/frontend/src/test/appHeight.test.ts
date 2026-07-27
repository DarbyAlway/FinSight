import { afterEach, expect, test, vi } from 'vitest';
import { installAppHeight } from '../lib/appHeight';

afterEach(() => {
  document.documentElement.style.removeProperty('--app-height');
});

test('sets --app-height from the visual viewport height', () => {
  const listeners: Record<string, () => void> = {};
  const fakeWindow = {
    document,
    innerHeight: 800,
    visualViewport: {
      height: 600,
      addEventListener: (evt: string, cb: () => void) => {
        listeners[evt] = cb;
      },
    },
    addEventListener: () => {},
  } as unknown as Window;

  installAppHeight(fakeWindow);
  expect(document.documentElement.style.getPropertyValue('--app-height')).toBe('600px');

  // Simulate the keyboard opening: visual viewport shrinks, resize fires.
  (fakeWindow.visualViewport as unknown as { height: number }).height = 350;
  listeners.resize();
  expect(document.documentElement.style.getPropertyValue('--app-height')).toBe('350px');
});

test('falls back to innerHeight when visualViewport is unavailable', () => {
  const fakeWindow = {
    document,
    innerHeight: 720,
    visualViewport: undefined,
    addEventListener: vi.fn(),
  } as unknown as Window;

  installAppHeight(fakeWindow);
  expect(document.documentElement.style.getPropertyValue('--app-height')).toBe('720px');
});
