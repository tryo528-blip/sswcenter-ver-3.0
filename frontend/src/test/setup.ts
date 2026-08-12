import * as matchers from '@testing-library/jest-dom/matchers';
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';
import { cleanup } from '@testing-library/react';
import { expect, afterEach } from 'vitest';

declare module 'vitest' {
  interface Assertion<T = any> extends TestingLibraryMatchers<Record<string, any>, T> {}
  interface AsymmetricMatchersContaining extends TestingLibraryMatchers<Record<string, any>, any> {}
}

expect.extend(matchers);

afterEach(() => {
  cleanup();
});
