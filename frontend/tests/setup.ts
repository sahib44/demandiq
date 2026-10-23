import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Chart drawing is covered in the real-browser suite. RTL exercises the
// application contracts without relying on jsdom layout measurements.
vi.mock('../src/components/Charts', () => ({
  DemandChart: () => null,
  MetricChart: () => null,
  CostChart: () => null,
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = '';
});
