import React, { useState } from 'react';
import { useAuth } from '../../context/useAuth';
import { validatePin } from '../../services/api';

export const BootstrapForm: React.FC = () => {
  const { submitBootstrap, error, isLoading, clearError } = useAuth();

  const [centerName, setCenterName] = useState('');
  const [adminName, setAdminName] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [sexCode, setSexCode] = useState('FEMALE');
  const [startDate, setStartDate] = useState('');
  const [pin, setPin] = useState('');
  const [confirmPin, setConfirmPin] = useState('');

  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    clearError();

    if (!centerName.trim()) {
      setFormError('센터명을 입력해주세요.');
      return;
    }
    if (!adminName.trim()) {
      setFormError('관리자명을 입력해주세요.');
      return;
    }
    if (!birthDate) {
      setFormError('생년월일을 입력해주세요.');
      return;
    }
    if (!sexCode) {
      setFormError('성별코드를 선택해주세요.');
      return;
    }
    if (!startDate) {
      setFormError('입사일을 입력해주세요.');
      return;
    }

    const pinVal = validatePin(pin);
    if (!pinVal.isValid) {
      setFormError(pinVal.message || '유효하지 않은 PIN 번호입니다.');
      return;
    }

    if (pin !== confirmPin) {
      setFormError('PIN 번호가 일치하지 않습니다.');
      return;
    }

    await submitBootstrap({
      center_name: centerName.trim(),
      admin_name: adminName.trim(),
      birth_date: birthDate,
      sex_code: sexCode,
      start_date: startDate,
      pin,
    });
  };

  const activeError = formError || error;

  return (
    <div className="auth-container" data-testid="bootstrap-container">
      <div className="auth-card auth-card-large">
        <div className="auth-header">
          <div className="auth-brand-logo">
            <span>SSWCenter</span>
            <span className="auth-brand-badge">Wave 0</span>
          </div>
          <h2 className="auth-title">최초 센터 설정</h2>
          <p className="auth-subtitle">
            사회복지 ERP 시스템 사용을 위한 초기 센터 및 관리자 정보를 등록하세요.
          </p>
        </div>

        {activeError && (
          <div
            className="auth-error-banner"
            style={{ marginBottom: '16px' }}
            data-testid="bootstrap-error"
          >
            {activeError}
          </div>
        )}

        <form
          className="auth-form"
          onSubmit={handleSubmit}
          data-testid="bootstrap-form"
          autoComplete="off"
        >
          <div className="auth-form-grid">
            <div className="auth-form-group auth-form-group-full">
              <label className="auth-label" htmlFor="center_name">
                센터명
              </label>
              <input
                id="center_name"
                type="text"
                className="auth-input"
                data-testid="bootstrap-center-name"
                value={centerName}
                onChange={(e) => setCenterName(e.target.value)}
                placeholder="예: 서울주간보호센터"
                disabled={isLoading}
              />
            </div>

            <div className="auth-form-group">
              <label className="auth-label" htmlFor="admin_name">
                관리자명
              </label>
              <input
                id="admin_name"
                type="text"
                className="auth-input"
                data-testid="bootstrap-admin-name"
                value={adminName}
                onChange={(e) => setAdminName(e.target.value)}
                placeholder="예: 홍길동"
                disabled={isLoading}
              />
            </div>

            <div className="auth-form-group">
              <label className="auth-label" htmlFor="sex_code">
                성별코드
              </label>
              <select
                id="sex_code"
                className="auth-select"
                data-testid="bootstrap-sex-code"
                value={sexCode}
                onChange={(e) => setSexCode(e.target.value)}
                disabled={isLoading}
              >
                <option value="FEMALE">여성 (FEMALE)</option>
                <option value="MALE">남성 (MALE)</option>
              </select>
            </div>

            <div className="auth-form-group">
              <label className="auth-label" htmlFor="birth_date">
                생년월일
              </label>
              <input
                id="birth_date"
                type="date"
                className="auth-input"
                data-testid="bootstrap-birth-date"
                value={birthDate}
                onChange={(e) => setBirthDate(e.target.value)}
                disabled={isLoading}
              />
            </div>

            <div className="auth-form-group">
              <label className="auth-label" htmlFor="start_date">
                입사일
              </label>
              <input
                id="start_date"
                type="date"
                className="auth-input"
                data-testid="bootstrap-start-date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                disabled={isLoading}
              />
            </div>

            <div className="auth-form-group">
              <label className="auth-label" htmlFor="pin">
                PIN 번호 (숫자 6자리)
              </label>
              <input
                id="pin"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                className="auth-input"
                data-testid="bootstrap-pin"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                placeholder="숫자 6자리"
                maxLength={6}
                disabled={isLoading}
              />
            </div>

            <div className="auth-form-group">
              <label className="auth-label" htmlFor="confirm_pin">
                PIN 번호 확인
              </label>
              <input
                id="confirm_pin"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                className="auth-input"
                data-testid="bootstrap-confirm-pin"
                value={confirmPin}
                onChange={(e) => setConfirmPin(e.target.value)}
                placeholder="PIN 번호 재입력"
                maxLength={6}
                disabled={isLoading}
              />
            </div>
          </div>

          <button
            type="submit"
            className="auth-submit-btn"
            data-testid="bootstrap-submit-btn"
            disabled={isLoading}
          >
            {isLoading ? '설정 저장 중...' : '최초 설정 완료'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default BootstrapForm;
