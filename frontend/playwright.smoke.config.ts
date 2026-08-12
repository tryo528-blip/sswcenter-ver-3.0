import { defineConfig } from 'playwright/test';
import baseConfig from './playwright.config';

export default defineConfig({
  ...baseConfig,
  testMatch: ['w1c-certification.spec.ts'],
});