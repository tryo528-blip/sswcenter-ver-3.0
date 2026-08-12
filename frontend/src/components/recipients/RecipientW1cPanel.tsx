import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../../services/api';
import {
  createApprovalAmountPeriod,
  createBenefitPeriod,
  createCertificationIdentity,
  createCertificationPeriod,
  createGradePeriod,
  getCertificationIdentity,
  invalidateApprovalAmountPeriod,
  invalidateBenefitPeriod,
  invalidateCertificationPeriod,
  invalidateGradePeriod,
  listApprovalAmountPeriods,
  listBenefitPeriods,
  listCertificationPeriods,
  listGradePeriods,
  normalizeApprovalAmountKrw,
  replaceApprovalAmountPeriod,
  replaceBenefitPeriod,
  replaceCertificationPeriod,
  replaceGradePeriod,
} from '../../services/w1cApi';
import type {
  ApprovalAmountPeriod,
  BenefitCode,
  BenefitPeriod,
  CertificationIdentity,
  CertificationPeriod,
  GradeCode,
  GradePeriod,
} from '../../services/w1cApi';

type RecipientW1cPanelProps = {
  recipientId: number | string;
};

type ClosedPeriodForm = {
  start_date: string;
  end_date: string;
};

type GradeForm = ClosedPeriodForm & {
  certification_period_id: string;
  grade_code: GradeCode;
};

type BenefitForm = {
  benefit_code: BenefitCode | '';
  start_date: string;
  end_date: string;
};

type ApprovalForm = {
  amount_krw: string;
  start_date: string;
  end_date: string;
};

const BENEFIT_OPTIONS: ReadonlyArray<{ value: BenefitCode; label: string }> = [
  { value: 'GENERAL', label: '일반' },
  { value: 'BASIC_LIVELIHOOD', label: '기초생활수급' },
  { value: 'REDUCTION_6', label: '감경 코드 6' },
  { value: 'REDUCTION_9', label: '감경 코드 9' },
  { value: 'MEDICAL_6', label: '의료 코드 6' },
  { value: 'MEDICAL_9', label: '의료 코드 9' },
];

const BENEFIT_LABELS = Object.fromEntries(
  BENEFIT_OPTIONS.map(({ value, label }) => [value, label]),
) as Record<BenefitCode, string>;

const emptyClosedPeriod = (): ClosedPeriodForm => ({ start_date: '', end_date: '' });
const emptyGrade = (): GradeForm => ({
  certification_period_id: '',
  grade_code: '1',
  start_date: '',
  end_date: '',
});
const emptyBenefit = (): BenefitForm => ({
  benefit_code: '',
  start_date: '',
  end_date: '',
});
const emptyApproval = (): ApprovalForm => ({
  amount_krw: '',
  start_date: '',
  end_date: '',
});

function canonicalPreview(value: string): string | null {
  const match = value.trim().match(/^[lL]([0-9]{10})(?:-[0-9]{3})?$/);
  return match ? `L${match[1]}` : null;
}

function periodText(startDate: string, endDate: string | null): string {
  return `${startDate} ~ ${endDate ?? '계속'}`;
}

function formatApprovalAmount(value: string): string {
  try {
    return BigInt(value).toLocaleString('ko-KR');
  } catch {
    return value;
  }
}

function historyState(
  invalidatedAt: string | null,
  replacementId: number | null,
): string {
  if (!invalidatedAt) return '유효';
  return replacementId ? `대체됨 → #${replacementId}` : '무효화됨';
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return '요청을 처리하지 못했습니다.';
}

const RecipientW1cPanel = ({ recipientId }: RecipientW1cPanelProps) => {
  const [identity, setIdentity] = useState<CertificationIdentity | null>(null);
  const [certificationPeriods, setCertificationPeriods] = useState<
    CertificationPeriod[]
  >([]);
  const [gradePeriods, setGradePeriods] = useState<GradePeriod[]>([]);
  const [benefitPeriods, setBenefitPeriods] = useState<BenefitPeriod[]>([]);
  const [approvalPeriods, setApprovalPeriods] = useState<ApprovalAmountPeriod[]>([]);
  const [identityInput, setIdentityInput] = useState('');
  const [certificationForm, setCertificationForm] =
    useState<ClosedPeriodForm>(emptyClosedPeriod);
  const [gradeForm, setGradeForm] = useState<GradeForm>(emptyGrade);
  const [benefitForm, setBenefitForm] = useState<BenefitForm>(emptyBenefit);
  const [approvalForm, setApprovalForm] = useState<ApprovalForm>(emptyApproval);
  const [editingCertificationId, setEditingCertificationId] = useState<number | null>(
    null,
  );
  const [editingGradeId, setEditingGradeId] = useState<number | null>(null);
  const [editingBenefitId, setEditingBenefitId] = useState<number | null>(null);
  const [editingApprovalId, setEditingApprovalId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const identityRequest = getCertificationIdentity(recipientId, signal).catch(
        (requestError: unknown) => {
          if (requestError instanceof ApiError && requestError.status === 404) return null;
          throw requestError;
        },
      );
      const [nextIdentity, certifications, grades, benefits, approvals] =
        await Promise.all([
          identityRequest,
          listCertificationPeriods(recipientId, signal),
          listGradePeriods(recipientId, signal),
          listBenefitPeriods(recipientId, signal),
          listApprovalAmountPeriods(recipientId, signal),
        ]);
      if (signal?.aborted) return;
      setIdentity(nextIdentity);
      setCertificationPeriods(certifications);
      setGradePeriods(grades);
      setBenefitPeriods(benefits);
      setApprovalPeriods(approvals);
    },
    [recipientId],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setMessage(null);
    setIdentity(null);
    setCertificationPeriods([]);
    setGradePeriods([]);
    setBenefitPeriods([]);
    setApprovalPeriods([]);
    setIdentityInput('');
    setCertificationForm(emptyClosedPeriod());
    setGradeForm(emptyGrade());
    setBenefitForm(emptyBenefit());
    setApprovalForm(emptyApproval());
    setEditingCertificationId(null);
    setEditingGradeId(null);
    setEditingBenefitId(null);
    setEditingApprovalId(null);

    void load(controller.signal)
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [load]);

  const refresh = async () => {
    await load();
  };

  const preview = useMemo(() => canonicalPreview(identityInput), [identityInput]);
  const activeCertifications = certificationPeriods.filter(
    (period) => !period.invalidated_at_utc,
  );

  const runMutation = async (
    action: () => Promise<unknown>,
    success: string,
  ): Promise<boolean> => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      await action();
      await refresh();
      setMessage(success);
      return true;
    } catch (requestError) {
      setError(errorMessage(requestError));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const handleIdentitySubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!preview) {
      setError('인정번호 형식을 확인하세요.');
      return;
    }
    void runMutation(
      () =>
        createCertificationIdentity(recipientId, {
          certification_number: identityInput,
        }),
      `인정 본번호 ${preview}을(를) 등록했습니다.`,
    );
  };

  const handleCertificationSubmit = (event: FormEvent) => {
    event.preventDefault();
    const editing = certificationPeriods.find(
      (period) => period.id === editingCertificationId,
    );
    void runMutation(
      () =>
        editing
          ? replaceCertificationPeriod(recipientId, editing.id, {
              ...certificationForm,
              expected_row_version: editing.row_version,
            })
          : createCertificationPeriod(recipientId, certificationForm),
      editing ? '인정기간을 정정했습니다.' : '인정기간을 등록했습니다.',
    ).then((succeeded) => {
      if (succeeded) {
        setEditingCertificationId(null);
        setCertificationForm(emptyClosedPeriod());
      }
    });
  };

  const handleGradeSubmit = (event: FormEvent) => {
    event.preventDefault();
    const certificationPeriodId = Number(gradeForm.certification_period_id);
    const editing = gradePeriods.find((period) => period.id === editingGradeId);
    const payload = {
      certification_period_id: certificationPeriodId,
      grade_code: gradeForm.grade_code,
      start_date: gradeForm.start_date,
      end_date: gradeForm.end_date,
    };
    void runMutation(
      () =>
        editing
          ? replaceGradePeriod(recipientId, editing.id, {
              ...payload,
              expected_row_version: editing.row_version,
            })
          : createGradePeriod(recipientId, payload),
      editing ? '등급기간을 정정했습니다.' : '등급기간을 등록했습니다.',
    ).then((succeeded) => {
      if (succeeded) {
        setEditingGradeId(null);
        setGradeForm(emptyGrade());
      }
    });
  };

  const handleBenefitSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!benefitForm.benefit_code) {
      setError('혜택 종류를 선택하세요.');
      return;
    }
    const editing = benefitPeriods.find((period) => period.id === editingBenefitId);
    const payload = {
      benefit_code: benefitForm.benefit_code,
      start_date: benefitForm.start_date,
      end_date: benefitForm.end_date || null,
    };
    void runMutation(
      () =>
        editing
          ? replaceBenefitPeriod(recipientId, editing.id, {
              ...payload,
              expected_row_version: editing.row_version,
            })
          : createBenefitPeriod(recipientId, payload),
      editing ? '혜택기간을 정정했습니다.' : '혜택기간을 등록했습니다.',
    ).then((succeeded) => {
      if (succeeded) {
        setEditingBenefitId(null);
        setBenefitForm(emptyBenefit());
      }
    });
  };

  const handleApprovalSubmit = (event: FormEvent) => {
    event.preventDefault();
    const amount = normalizeApprovalAmountKrw(approvalForm.amount_krw);
    if (amount === null) {
      setError(
        '승인금액은 0 이상 9,223,372,036,854,775,807 이하의 정수 원 단위로 입력하세요.',
      );
      return;
    }
    const editing = approvalPeriods.find((period) => period.id === editingApprovalId);
    const payload = {
      amount_krw: amount,
      start_date: approvalForm.start_date,
      end_date: approvalForm.end_date || null,
    };
    void runMutation(
      () =>
        editing
          ? replaceApprovalAmountPeriod(recipientId, editing.id, {
              ...payload,
              expected_row_version: editing.row_version,
            })
          : createApprovalAmountPeriod(recipientId, payload),
      editing ? '승인금액 기간을 정정했습니다.' : '승인금액 기간을 등록했습니다.',
    ).then((succeeded) => {
      if (succeeded) {
        setEditingApprovalId(null);
        setApprovalForm(emptyApproval());
      }
    });
  };

  const startCertificationEdit = (period: CertificationPeriod) => {
    setEditingCertificationId(period.id);
    setCertificationForm({
      start_date: period.start_date,
      end_date: period.end_date,
    });
  };

  const startGradeEdit = (period: GradePeriod) => {
    setEditingGradeId(period.id);
    setGradeForm({
      certification_period_id: String(period.certification_period_id),
      grade_code: period.grade_code,
      start_date: period.start_date,
      end_date: period.end_date,
    });
  };

  const startBenefitEdit = (period: BenefitPeriod) => {
    setEditingBenefitId(period.id);
    setBenefitForm({
      benefit_code: period.benefit_code,
      start_date: period.start_date,
      end_date: period.end_date ?? '',
    });
  };

  const startApprovalEdit = (period: ApprovalAmountPeriod) => {
    setEditingApprovalId(period.id);
    setApprovalForm({
      amount_krw: period.amount_krw,
      start_date: period.start_date,
      end_date: period.end_date ?? '',
    });
  };

  return (
    <section className="recipient-w1c-panel" data-testid="w1c-panel">
      <div className="recipient-subsection-heading">
        <div>
          <h3>인정·등급·혜택·승인금액</h3>
          <span>유효기간과 정정 이력을 분리해 관리합니다.</span>
        </div>
        {loading ? <span>불러오는 중…</span> : null}
      </div>

      {error ? (
        <div className="recipient-inline-error" data-testid="w1c-error">
          {error}
        </div>
      ) : null}
      {message ? (
        <div className="recipient-inline-note" data-testid="w1c-message">
          {message}
        </div>
      ) : null}

      <div className="recipient-w1c-grid">
        <section className="recipient-subsection" data-testid="w1c-certification-section">
          <div className="recipient-subsection-heading">
            <h3>인정 본번호·기간</h3>
            <span>{identity ? identity.certification_number : '미등록'}</span>
          </div>
          {!identity ? (
            <form className="recipient-w1c-form" onSubmit={handleIdentitySubmit}>
              <label className="recipient-field">
                인정번호 <em>필수</em>
                <input
                  data-testid="w1c-certification-input"
                  data-detail-batch-field="true"
                  value={identityInput}
                  onChange={(event) => setIdentityInput(event.target.value)}
                  placeholder="L1234567890 또는 l1234567890-100"
                  required
                  disabled={saving}
                />
              </label>
              <div className="recipient-muted">
                L + 숫자 10자리로 저장하며, 소문자 l과 3자리 suffix는 본번호로
                정규화합니다.
              </div>
              <strong data-testid="w1c-certification-preview">
                저장될 본번호: {preview ?? '형식을 확인하세요'}
              </strong>
              <button
                className="recipient-secondary-button"
                type="submit"
                disabled={saving || !preview}
              >
                인정 본번호 등록
              </button>
            </form>
          ) : null}

          <div className="recipient-history-list" data-testid="w1c-certification-history">
            {certificationPeriods.length ? (
              certificationPeriods.map((period) => (
                <article className="recipient-history-card" key={period.id}>
                  <strong>{periodText(period.start_date, period.end_date)}</strong>
                  <span>
                    {historyState(
                      period.invalidated_at_utc,
                      period.replacement_certification_period_id,
                    )}
                  </span>
                  {!period.invalidated_at_utc ? (
                    <div className="recipient-history-card-actions">
                      <button
                        type="button"
                        onClick={() => startCertificationEdit(period)}
                        disabled={saving}
                      >
                        정정
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void runMutation(
                            () =>
                              invalidateCertificationPeriod(recipientId, period.id, {
                                expected_row_version: period.row_version,
                              }),
                            '인정기간을 무효화했습니다.',
                          )
                        }
                        disabled={saving}
                      >
                        무효화
                      </button>
                    </div>
                  ) : null}
                </article>
              ))
            ) : (
              <div className="recipient-muted">등록된 인정기간이 없습니다.</div>
            )}
          </div>

          <form className="recipient-w1c-form" onSubmit={handleCertificationSubmit}>
            <div className="recipient-form-grid">
              <label className="recipient-field">
                시작일 <em>필수</em>
                <input
                  data-testid="w1c-certification-start-date"
                  data-detail-batch-field="true"
                  data-period-id={editingCertificationId ?? undefined}
                  data-row-version={
                    certificationPeriods.find((item) => item.id === editingCertificationId)
                      ?.row_version
                  }
                  type="date"
                  value={certificationForm.start_date}
                  onChange={(event) =>
                    setCertificationForm((current) => ({
                      ...current,
                      start_date: event.target.value,
                    }))
                  }
                  required
                  disabled={!identity || saving}
                />
              </label>
              <label className="recipient-field">
                종료일 <em>필수</em>
                <input
                  data-testid="w1c-certification-end-date"
                  type="date"
                  value={certificationForm.end_date}
                  onChange={(event) =>
                    setCertificationForm((current) => ({
                      ...current,
                      end_date: event.target.value,
                    }))
                  }
                  required
                  disabled={!identity || saving}
                />
              </label>
            </div>
            <div className="recipient-history-card-actions">
              <button
                className="recipient-secondary-button"
                type="submit"
                disabled={!identity || saving}
              >
                {editingCertificationId ? '인정기간 정정' : '인정기간 등록'}
              </button>
              {editingCertificationId ? (
                <button
                  type="button"
                  onClick={() => {
                    setEditingCertificationId(null);
                    setCertificationForm(emptyClosedPeriod());
                  }}
                >
                  취소
                </button>
              ) : null}
            </div>
          </form>
        </section>

        <section className="recipient-subsection" data-testid="w1c-grade-section">
          <div className="recipient-subsection-heading">
            <h3>등급기간</h3>
            <span>1~5 등급만 사용</span>
          </div>
          <div className="recipient-history-list" data-testid="w1c-grade-history">
            {gradePeriods.length ? (
              gradePeriods.map((period) => (
                <article className="recipient-history-card" key={period.id}>
                  <strong>{period.grade_code}등급</strong>
                  <span>{periodText(period.start_date, period.end_date)}</span>
                  <span>
                    {historyState(
                      period.invalidated_at_utc,
                      period.replacement_grade_period_id,
                    )}
                  </span>
                  {!period.invalidated_at_utc ? (
                    <div className="recipient-history-card-actions">
                      <button
                        type="button"
                        onClick={() => startGradeEdit(period)}
                        disabled={saving}
                      >
                        정정
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void runMutation(
                            () =>
                              invalidateGradePeriod(recipientId, period.id, {
                                expected_row_version: period.row_version,
                              }),
                            '등급기간을 무효화했습니다.',
                          )
                        }
                        disabled={saving}
                      >
                        무효화
                      </button>
                    </div>
                  ) : null}
                </article>
              ))
            ) : (
              <div className="recipient-muted">등록된 등급기간이 없습니다.</div>
            )}
          </div>
          <form className="recipient-w1c-form" onSubmit={handleGradeSubmit}>
            <div className="recipient-form-grid">
              <label className="recipient-field recipient-field-wide">
                인정기간 <em>필수</em>
                <select
                  data-testid="w1c-grade-certification-select"
                  value={gradeForm.certification_period_id}
                  onChange={(event) =>
                    setGradeForm((current) => ({
                      ...current,
                      certification_period_id: event.target.value,
                    }))
                  }
                  required
                  disabled={!activeCertifications.length || saving}
                >
                  <option value="">인정기간 선택</option>
                  {activeCertifications.map((period) => (
                    <option key={period.id} value={period.id}>
                      {periodText(period.start_date, period.end_date)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="recipient-field">
                등급 <em>필수</em>
                <select
                  data-testid="w1c-grade-select"
                  value={gradeForm.grade_code}
                  onChange={(event) =>
                    setGradeForm((current) => ({
                      ...current,
                      grade_code: event.target.value as GradeCode,
                    }))
                  }
                  required
                  disabled={!activeCertifications.length || saving}
                >
                  {(['1', '2', '3', '4', '5'] as const).map((grade) => (
                    <option key={grade} value={grade}>
                      {grade}
                    </option>
                  ))}
                </select>
              </label>
              <label className="recipient-field">
                시작일 <em>필수</em>
                <input
                  data-testid="w1c-grade-start-date"
                  data-detail-batch-field="true"
                  data-period-id={editingGradeId ?? undefined}
                  data-row-version={
                    gradePeriods.find((item) => item.id === editingGradeId)?.row_version
                  }
                  type="date"
                  value={gradeForm.start_date}
                  onChange={(event) =>
                    setGradeForm((current) => ({
                      ...current,
                      start_date: event.target.value,
                    }))
                  }
                  required
                  disabled={!activeCertifications.length || saving}
                />
              </label>
              <label className="recipient-field">
                종료일 <em>필수</em>
                <input
                  data-testid="w1c-grade-end-date"
                  type="date"
                  value={gradeForm.end_date}
                  onChange={(event) =>
                    setGradeForm((current) => ({
                      ...current,
                      end_date: event.target.value,
                    }))
                  }
                  required
                  disabled={!activeCertifications.length || saving}
                />
              </label>
            </div>
            <div className="recipient-history-card-actions">
              <button
                className="recipient-secondary-button"
                type="submit"
                disabled={!activeCertifications.length || saving}
              >
                {editingGradeId ? '등급기간 정정' : '등급기간 등록'}
              </button>
              {editingGradeId ? (
                <button
                  type="button"
                  onClick={() => {
                    setEditingGradeId(null);
                    setGradeForm(emptyGrade());
                  }}
                >
                  취소
                </button>
              ) : null}
            </div>
          </form>
        </section>

        <section className="recipient-subsection" data-testid="w1c-benefit-section">
          <div className="recipient-subsection-heading">
            <h3>혜택기간</h3>
            <span>자료 없음은 일반으로 간주하지 않음</span>
          </div>
          <div className="recipient-history-list" data-testid="w1c-benefit-history">
            {benefitPeriods.length ? (
              benefitPeriods.map((period) => (
                <article className="recipient-history-card" key={period.id}>
                  <strong>{BENEFIT_LABELS[period.benefit_code]}</strong>
                  <span>{period.benefit_code}</span>
                  <span>{periodText(period.start_date, period.end_date)}</span>
                  <span>
                    {historyState(
                      period.invalidated_at_utc,
                      period.replacement_benefit_period_id,
                    )}
                  </span>
                  {!period.invalidated_at_utc ? (
                    <div className="recipient-history-card-actions">
                      <button
                        type="button"
                        onClick={() => startBenefitEdit(period)}
                        disabled={saving}
                      >
                        정정
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void runMutation(
                            () =>
                              invalidateBenefitPeriod(recipientId, period.id, {
                                expected_row_version: period.row_version,
                              }),
                            '혜택기간을 무효화했습니다.',
                          )
                        }
                        disabled={saving}
                      >
                        무효화
                      </button>
                    </div>
                  ) : null}
                </article>
              ))
            ) : (
              <div className="recipient-muted" data-testid="w1c-benefit-empty">
                적용 혜택 자료가 없습니다.
              </div>
            )}
          </div>
          <form className="recipient-w1c-form" onSubmit={handleBenefitSubmit}>
            <div className="recipient-form-grid">
              <label className="recipient-field recipient-field-wide">
                혜택 종류 <em>필수</em>
                <select
                  data-testid="w1c-benefit-select"
                  value={benefitForm.benefit_code}
                  onChange={(event) =>
                    setBenefitForm((current) => ({
                      ...current,
                      benefit_code: event.target.value as BenefitCode | '',
                    }))
                  }
                  required
                  disabled={saving}
                >
                  <option value="">혜택 선택</option>
                  {BENEFIT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="recipient-field">
                시작일 <em>필수</em>
                <input
                  data-testid="w1c-benefit-start-date"
                  data-detail-batch-field="true"
                  data-period-id={editingBenefitId ?? undefined}
                  data-row-version={
                    benefitPeriods.find((item) => item.id === editingBenefitId)?.row_version
                  }
                  type="date"
                  value={benefitForm.start_date}
                  onChange={(event) =>
                    setBenefitForm((current) => ({
                      ...current,
                      start_date: event.target.value,
                    }))
                  }
                  required
                  disabled={saving}
                />
              </label>
              <label className="recipient-field">
                종료일
                <input
                  data-testid="w1c-benefit-end-date"
                  type="date"
                  value={benefitForm.end_date}
                  onChange={(event) =>
                    setBenefitForm((current) => ({
                      ...current,
                      end_date: event.target.value,
                    }))
                  }
                  disabled={saving}
                />
              </label>
            </div>
            <div className="recipient-history-card-actions">
              <button
                className="recipient-secondary-button"
                type="submit"
                disabled={saving || !benefitForm.benefit_code}
              >
                {editingBenefitId ? '혜택기간 정정' : '혜택기간 등록'}
              </button>
              {editingBenefitId ? (
                <button
                  type="button"
                  onClick={() => {
                    setEditingBenefitId(null);
                    setBenefitForm(emptyBenefit());
                  }}
                >
                  취소
                </button>
              ) : null}
            </div>
          </form>
        </section>

        <section className="recipient-subsection" data-testid="w1c-approval-section">
          <div className="recipient-subsection-heading">
            <h3>지자체 승인금액</h3>
            <span>혜택과 독립된 원 단위 기간원장</span>
          </div>
          <div className="recipient-history-list" data-testid="w1c-approval-history">
            {approvalPeriods.length ? (
              approvalPeriods.map((period) => (
                <article className="recipient-history-card" key={period.id}>
                  <strong>{formatApprovalAmount(period.amount_krw)}원</strong>
                  <span>{periodText(period.start_date, period.end_date)}</span>
                  <span>
                    {historyState(
                      period.invalidated_at_utc,
                      period.replacement_local_approval_amount_period_id,
                    )}
                  </span>
                  {!period.invalidated_at_utc ? (
                    <div className="recipient-history-card-actions">
                      <button
                        type="button"
                        onClick={() => startApprovalEdit(period)}
                        disabled={saving}
                      >
                        정정
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void runMutation(
                            () =>
                              invalidateApprovalAmountPeriod(recipientId, period.id, {
                                expected_row_version: period.row_version,
                              }),
                            '승인금액 기간을 무효화했습니다.',
                          )
                        }
                        disabled={saving}
                      >
                        무효화
                      </button>
                    </div>
                  ) : null}
                </article>
              ))
            ) : (
              <div className="recipient-muted">등록된 승인금액 기간이 없습니다.</div>
            )}
          </div>
          <form className="recipient-w1c-form" onSubmit={handleApprovalSubmit}>
            <div className="recipient-form-grid">
              <label className="recipient-field recipient-field-wide">
                승인금액(원) <em>필수</em>
                <input
                  data-testid="w1c-approval-amount-input"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]+"
                  value={approvalForm.amount_krw}
                  onChange={(event) =>
                    setApprovalForm((current) => ({
                      ...current,
                      amount_krw: event.target.value,
                    }))
                  }
                  required
                  disabled={saving}
                />
              </label>
              <label className="recipient-field">
                시작일 <em>필수</em>
                <input
                  data-testid="w1c-approval-start-date"
                  data-detail-batch-field="true"
                  data-period-id={editingApprovalId ?? undefined}
                  data-row-version={
                    approvalPeriods.find((item) => item.id === editingApprovalId)?.row_version
                  }
                  type="date"
                  value={approvalForm.start_date}
                  onChange={(event) =>
                    setApprovalForm((current) => ({
                      ...current,
                      start_date: event.target.value,
                    }))
                  }
                  required
                  disabled={saving}
                />
              </label>
              <label className="recipient-field">
                종료일
                <input
                  data-testid="w1c-approval-end-date"
                  type="date"
                  value={approvalForm.end_date}
                  onChange={(event) =>
                    setApprovalForm((current) => ({
                      ...current,
                      end_date: event.target.value,
                    }))
                  }
                  disabled={saving}
                />
              </label>
            </div>
            <div className="recipient-history-card-actions">
              <button
                className="recipient-secondary-button"
                type="submit"
                disabled={saving}
              >
                {editingApprovalId ? '승인금액 기간 정정' : '승인금액 기간 등록'}
              </button>
              {editingApprovalId ? (
                <button
                  type="button"
                  onClick={() => {
                    setEditingApprovalId(null);
                    setApprovalForm(emptyApproval());
                  }}
                >
                  취소
                </button>
              ) : null}
            </div>
          </form>
        </section>
      </div>
    </section>
  );
};

export default RecipientW1cPanel;
