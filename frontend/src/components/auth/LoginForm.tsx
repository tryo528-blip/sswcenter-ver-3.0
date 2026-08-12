import React, { useEffect, useState } from 'react';
import { getMonthlyColorToken } from '../../design-system/tokens';
import { useAuth } from '../../context/useAuth';
import { validatePin } from '../../services/api';

const LOGIN_WHALE_POSITIONS = [
  'bottom-right',
  'bottom-left',
  'top-right',
  'top-left',
] as const;
// Scale relative to the current whale size: 50%, 70%, and 100%.
const LOGIN_WHALE_SIZES = ['small', 'medium', 'full'] as const;
const LOGIN_PIN_LENGTH = 6;

type LoginWhaleDisplayGroup = 'hi' | 'mid' | 'low';
type LoginWhaleSize = (typeof LOGIN_WHALE_SIZES)[number];

type LoginWhaleAsset = {
  src: string;
  displayGroup: LoginWhaleDisplayGroup;
  displayScale: number;
  aspectRatio: number;
  allowedSizes: readonly LoginWhaleSize[];
  sourceWidth?: number;
};

const LOGIN_WHALE_IMAGES: readonly LoginWhaleAsset[] = [
  // The login set is an explicit manifest so Drive filenames do not depend on the old hi/mid/low numbering.
  { src: '/assets/login-whales/whale_01.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_02.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_03.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_04.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_05.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_06.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_07.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_08.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_09.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 564, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_10.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 833 / 647, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 833 },
  { src: '/assets/login-whales/whale_11.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 1080 / 1457, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1080 },
  { src: '/assets/login-whales/whale_12.png', displayGroup: 'mid', displayScale: 0.95, aspectRatio: 770 / 200, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 770 },
  { src: '/assets/login-whales/whale_13.png', displayGroup: 'mid', displayScale: 0.95, aspectRatio: 709 / 223, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 709 },
  { src: '/assets/login-whales/whale_14.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 522 / 455, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 522 },
  { src: '/assets/login-whales/whale_15.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 471 / 610, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 471 },
  { src: '/assets/login-whales/whale_16.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 834 / 647, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 834 },
  { src: '/assets/login-whales/whale_17.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 667 / 647, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 667 },
  { src: '/assets/login-whales/whale_18.png', displayGroup: 'hi', displayScale: 0.9, aspectRatio: 1034 / 491, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1034 },
  { src: '/assets/login-whales/whale_19.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 833 / 647, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 833 },
  { src: '/assets/login-whales/whale_20.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 640 / 647, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 640 },
  { src: '/assets/login-whales/whale_21.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 1252 / 832, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1252 },
  { src: '/assets/login-whales/whale_22.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 1264 / 846, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1264 },
  { src: '/assets/login-whales/whale_23.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 1056 / 1024, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1056 },
  { src: '/assets/login-whales/whale_24.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 1264 / 846, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1264 },
  { src: '/assets/login-whales/whale_25.png', displayGroup: 'mid', displayScale: 0.85, aspectRatio: 1056 / 1024, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1056 },
  { src: '/assets/login-whales/whale_26.png', displayGroup: 'mid', displayScale: 0.8, aspectRatio: 1408 / 768, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1408 },
  { src: '/assets/login-whales/whale_27.png', displayGroup: 'mid', displayScale: 0.8, aspectRatio: 783 / 1376, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 783 },
  { src: '/assets/login-whales/whale_28.png', displayGroup: 'mid', displayScale: 0.8, aspectRatio: 1408 / 768, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1408 },
  { src: '/assets/login-whales/whale_29.png', displayGroup: 'mid', displayScale: 0.8, aspectRatio: 1408 / 768, allowedSizes: LOGIN_WHALE_SIZES, sourceWidth: 1408 },
];

const LOGIN_WHALE_SIZE_SCALES: Record<(typeof LOGIN_WHALE_SIZES)[number], number> = {
  small: 0.5,
  medium: 0.7,
  full: 1,
};

type LoginGradient = {
  start: string;
  mid: string;
  end: string;
  glow: string;
  glowPosition: string;
  angle: string;
  sheenAngle: string;
};

const MONTHLY_LOGIN_GRADIENTS: Record<number, LoginGradient> = {
  1: { start: '#f1f6ff', mid: '#c4dbff', end: '#b4ccfb', glow: '#ffffff', glowPosition: '18% 18%', angle: '135deg', sheenAngle: '135deg' },
  2: { start: '#f7f2ff', mid: '#dfceff', end: '#d1baff', glow: '#ffffff', glowPosition: '82% 16%', angle: '225deg', sheenAngle: '225deg' },
  3: { start: '#effff7', mid: '#c5efda', end: '#abe5c6', glow: '#ffffff', glowPosition: '20% 76%', angle: '135deg', sheenAngle: '135deg' },
  4: { start: '#fff2f7', mid: '#ffcadf', end: '#ffb4d0', glow: '#ffffff', glowPosition: '82% 24%', angle: '225deg', sheenAngle: '225deg' },
  5: { start: '#effdfb', mid: '#beeae3', end: '#a7dfd6', glow: '#ffffff', glowPosition: '24% 20%', angle: '135deg', sheenAngle: '135deg' },
  6: { start: '#edfaff', mid: '#b8e5f8', end: '#a0d8f3', glow: '#ffffff', glowPosition: '74% 72%', angle: '225deg', sheenAngle: '225deg' },
  7: { start: '#effcf9', mid: '#b7e7dc', end: '#9fdacd', glow: '#ffffff', glowPosition: '18% 78%', angle: '135deg', sheenAngle: '135deg' },
  8: { start: '#eef3ff', mid: '#c4d5ff', end: '#adc3f7', glow: '#ffffff', glowPosition: '82% 18%', angle: '225deg', sheenAngle: '225deg' },
  9: { start: '#fff9e8', mid: '#ffdfaa', end: '#f7ce88', glow: '#ffffff', glowPosition: '80% 74%', angle: '135deg', sheenAngle: '135deg' },
  10: { start: '#fff5e9', mid: '#ffd3ae', end: '#f9bd8b', glow: '#ffffff', glowPosition: '20% 22%', angle: '225deg', sheenAngle: '225deg' },
  11: { start: '#fcf4ed', mid: '#e5ccb2', end: '#d5ad8c', glow: '#ffffff', glowPosition: '78% 20%', angle: '135deg', sheenAngle: '135deg' },
  12: { start: '#effaf1', mid: '#f0b2bb', end: '#b2d5b8', glow: '#fff8f6', glowPosition: '22% 76%', angle: '225deg', sheenAngle: '225deg' },
};

function getLoginGradient(month: number): LoginGradient {
  return MONTHLY_LOGIN_GRADIENTS[month] || MONTHLY_LOGIN_GRADIENTS[8];
}

function getLoginMonth(): number {
  const actualMonth = new Date().getMonth() + 1;
  if (!import.meta.env.DEV) return actualMonth;

  const requestedMonth = Number(new URLSearchParams(window.location.search).get('previewMonth'));
  return Number.isInteger(requestedMonth) && requestedMonth >= 1 && requestedMonth <= 12
    ? requestedMonth
    : actualMonth;
}

function pickRandom<T>(items: readonly T[]): T {
  return items[Math.floor(Math.random() * items.length)]!;
}

function getViewportSize() {
  return {
    width: typeof window === 'undefined' ? 1280 : window.innerWidth,
    height: typeof window === 'undefined' ? 720 : window.innerHeight,
  };
}

export const LoginForm: React.FC = () => {
  const { login, isLoading, clearError } = useAuth();
  const [pin, setPin] = useState('');
  const [whaleAsset] = useState(() => pickRandom(LOGIN_WHALE_IMAGES));
  const [whaleAspectRatio, setWhaleAspectRatio] = useState(whaleAsset.aspectRatio);
  const [whalePosition] = useState(() => pickRandom(LOGIN_WHALE_POSITIONS));
  const [whaleSize] = useState(() => pickRandom(whaleAsset.allowedSizes));
  const [whaleNaturalWidth, setWhaleNaturalWidth] = useState(0);
  const [viewportSize, setViewportSize] = useState(getViewportSize);

  useEffect(() => {
    const handleResize = () => setViewportSize(getViewportSize());
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const submitPin = async (candidatePin: string) => {
    clearError();

    if (candidatePin.length !== LOGIN_PIN_LENGTH || !validatePin(candidatePin).isValid) {
      return;
    }

    await login(candidatePin);
  };

  const handlePinChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nextPin = e.target.value;
    setPin(nextPin);
    if (nextPin.length === LOGIN_PIN_LENGTH) {
      void submitPin(nextPin);
    }
  };

  const currentMonth = getLoginMonth();
  const authTheme = getMonthlyColorToken(currentMonth);
  const loginGradient = getLoginGradient(currentMonth);
  const whaleScale = LOGIN_WHALE_SIZE_SCALES[whaleSize] * whaleAsset.displayScale;
  const whaleHorizontalMargin = viewportSize.width <= 640
    ? 16
    : Math.min(64, Math.max(16, viewportSize.width * 0.04));
  const whaleVerticalMargin = viewportSize.width <= 640
    ? 16
    : Math.min(48, Math.max(16, viewportSize.height * 0.04));
  const whaleAvailableHeight = Math.max(0, viewportSize.height - whaleVerticalMargin * 2);
  const whaleBaseWidth = Math.max(
    0,
    Math.min(
      viewportSize.width * (viewportSize.width <= 640 ? 0.92 : 0.78),
      820,
      viewportSize.width - whaleHorizontalMargin * 2,
      (whaleAvailableHeight * whaleAspectRatio) / whaleScale,
    ),
  );
  const whaleRenderWidth = whaleBaseWidth * whaleScale;
  const whaleSourceWidth = whaleNaturalWidth > 0
    ? whaleNaturalWidth
    : whaleAsset.sourceWidth ?? Number.POSITIVE_INFINITY;
  const cappedWhaleRenderWidth = Math.min(
    whaleRenderWidth,
    whaleSourceWidth,
  );
  const loginThemeStyle = {
    '--auth-theme': authTheme.hex,
    '--auth-gradient-start': loginGradient.start,
    '--auth-gradient-mid': loginGradient.mid,
    '--auth-gradient-end': loginGradient.end,
    '--auth-gradient-glow': loginGradient.glow,
    '--auth-gradient-glow-position': loginGradient.glowPosition,
    '--auth-gradient-angle': loginGradient.angle,
    '--auth-gradient-sheen-angle': loginGradient.sheenAngle,
  } as React.CSSProperties;

  return (
    <div
      className="auth-container auth-login-container"
      data-testid="login-container"
      data-theme-month={currentMonth}
      style={loginThemeStyle}
    >
      <div
        className={`auth-login-whale auth-login-whale--${whalePosition} auth-login-whale--size-${whaleSize}`}
        data-whale-position={whalePosition}
        data-whale-size={whaleSize}
        data-whale-display-group={whaleAsset.displayGroup}
        style={{
          width: `${cappedWhaleRenderWidth}px`,
          visibility: whaleNaturalWidth > 0 ? 'visible' : 'hidden',
        }}
        aria-hidden="true"
      >
        <img
          src={whaleAsset.src}
          alt=""
          data-testid="login-whale-image"
          onLoad={(event) => {
            const image = event.currentTarget;
            if (image.naturalWidth > 0 && image.naturalHeight > 0) {
              setWhaleAspectRatio(image.naturalWidth / image.naturalHeight);
              setWhaleNaturalWidth(image.naturalWidth);
            }
          }}
        />
      </div>

      <div className="auth-card auth-login-card">
        <div
          className="auth-form auth-login-form"
          data-testid="login-form"
          aria-busy={isLoading}
        >
          <div className="auth-form-group auth-login-form-group">
            <label className="auth-label auth-visually-hidden" htmlFor="login_pin">
              PIN 번호
            </label>
            <input
              id="login_pin"
              type="password"
              inputMode="numeric"
              autoComplete="off"
              className="auth-input auth-login-input"
              data-testid="login-pin-input"
              aria-label="PIN 번호"
              aria-invalid="false"
              maxLength={LOGIN_PIN_LENGTH}
              value={pin}
              onChange={handlePinChange}
              autoFocus
              disabled={isLoading}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoginForm;
