import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';

const fontCss = readFileSync(
  resolve(process.cwd(), 'src/styles/fonts.css'),
  'utf8',
);
const tokenCss = readFileSync(
  resolve(process.cwd(), 'src/styles/tokens.css'),
  'utf8',
);

describe('Local Font Contract (Pretendard with serif fallbacks)', () => {
  it('defines MaruBuri @font-face rules with local path contract', () => {
    expect(fontCss).toContain("font-family: 'MaruBuri'");
    expect(fontCss).toContain("url('/fonts/MaruBuri-Regular.woff2')");
    expect(fontCss).toContain("url('/fonts/MaruBuri-Bold.woff2')");
  });

  it('defines every bundled Pretendard weight with local paths', () => {
    for (const [weight, file] of [
      [100, 'Pretendard-Thin.woff2'],
      [200, 'Pretendard-ExtraLight.woff2'],
      [300, 'Pretendard-Light.woff2'],
      [400, 'Pretendard-Regular.woff2'],
      [500, 'Pretendard-Medium.woff2'],
      [600, 'Pretendard-SemiBold.woff2'],
      [700, 'Pretendard-Bold.woff2'],
      [800, 'Pretendard-ExtraBold.woff2'],
      [900, 'Pretendard-Black.woff2'],
    ] as const) {
      expect(fontCss).toContain(`font-weight: ${weight};`);
      expect(fontCss).toContain(`url('/fonts/${file}')`);
    }
  });

  it('loads every bundled MaruBuri weight instead of synthesizing missing weights', () => {
    for (const [weight, file] of [
      [200, 'MaruBuri-ExtraLight.woff2'],
      [300, 'MaruBuri-Light.woff2'],
      [400, 'MaruBuri-Regular.woff2'],
      [600, 'MaruBuri-SemiBold.woff2'],
      [700, 'MaruBuri-Bold.woff2'],
    ] as const) {
      expect(fontCss).toContain(`font-weight: ${weight};`);
      expect(fontCss).toContain(`url('/fonts/${file}')`);
    }
  });

  it('does NOT contain any external CDN, Google Fonts, or remote HTTP URL', () => {
    expect(fontCss).not.toContain('http://');
    expect(fontCss).not.toContain('https://');
    expect(fontCss).not.toContain('cdn');
    expect(fontCss).not.toContain('googleapis.com');
  });

  it('applies Pretendard globally with local fallbacks', () => {
    expect(fontCss).toContain("font-family: var(--font-family-base, 'Pretendard'");
  });

  it('uses the serif contract for numerals, controls, and formerly monospaced text', () => {
    expect(tokenCss).toContain("--font-family-base: 'Pretendard', 'Noto Serif KR', 'NotoSerifKR', 'MaruBuri', serif");
    expect(tokenCss).toContain('--font-family-mono: var(--font-family-base)');
    expect(tokenCss).not.toContain('Consolas');
    expect(tokenCss).not.toContain('Courier');
    expect(fontCss).toContain('code,');
    expect(fontCss).toContain('input,');
    expect(fontCss).toContain('font-synthesis: none');
  });
});
