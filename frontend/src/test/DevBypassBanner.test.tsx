import './setup';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DevBypassBanner } from '../components/common/DevBypassBanner';

describe('DevBypassBanner', () => {
  it('is not shown when bypass is disabled', () => {
    render(<DevBypassBanner enabled={false} />);

    expect(screen.queryByTestId('dev-bypass-banner')).not.toBeInTheDocument();
  });

  it('shows the active state text when explicitly enabled', () => {
    render(<DevBypassBanner enabled />);

    expect(screen.getByTestId('dev-bypass-banner')).toHaveTextContent(
      '로그인 우회: 사용 중',
    );
  });
});
