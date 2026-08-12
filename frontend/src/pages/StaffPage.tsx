import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import {
  ApiError,
  AUTH_SESSION_CHANGED_EVENT,
  AUTH_SESSION_READY_EVENT,
} from '../services/api';
import {
  closeStaffServiceQualification,
  closeEmployment,
  createStaffHealthCheck,
  createStaffLicense,
  createStaffPeriodicTraining,
  createStaffServiceQualification,
  createEmployment,
  createStaff,
  createStaffQuarterlyConsultation,
  fetchLicenseTypes,
  fetchSessionCapabilities,
  fetchServiceCatalog,
  fetchStaffDetail,
  fetchStaffHealthCheckRequirements,
  fetchStaffHealthChecks,
  fetchStaffLicenses,
  fetchStaffList,
  fetchStaffOnboardingTrainings,
  fetchStaffPeriodicTrainings,
  fetchStaffQuarterlyConsultations,
  fetchStaffServiceQualifications,
  fetchTrainingCourses,
  ConsultationApiError,
  HealthApiError,
  invalidateStaffLicense,
  invalidateStaffHealthCheck,
  invalidateStaffHealthCheckRequirement,
  invalidateStaffPeriodicTraining,
  invalidateStaffServiceQualification,
  invalidateStaffQuarterlyConsultation,
  revealSensitiveIdentity,
  replaceStaffLicense,
  replaceStaffServiceQualification,
  updateStaffHealthCheck,
  updateStaffHealthCheckRequirement,
  updateStaffOnboardingTraining,
  updateStaffPeriodicTraining,
  updateStaffQuarterlyConsultation,
  type StaffCreateRequest,
  type StaffEmploymentCloseRequest,
  type StaffLicenseCreateRequest,
  type StaffLicenseInvalidateRequest,
  type StaffLicenseReplacementRequest,
  type StaffLicenseResponse,
  type StaffHealthCheckCreateRequest,
  type StaffHealthCheckRequirementResponse,
  type StaffHealthCheckRequirementUpdateRequest,
  type StaffHealthCheckResponse,
  type StaffHealthCheckUpdateRequest,
  type HealthCheckRequirementStatus,
  type QuarterlyConsultationStatus,
  type StaffQuarterlyConsultationCreateRequest,
  type StaffQuarterlyConsultationReplaceRequest,
  type StaffQuarterlyConsultationResponse,
  type StaffQuarterlyConsultationUpdateRequest,
  type StaffOnboardingTrainingUpdateRequest,
  type StaffPeriodicTrainingCreateRequest,
  type StaffPeriodicTrainingInvalidateRequest,
  type StaffOnboardingTrainingResponse,
  type StaffPeriodicTrainingResponse,
  type StaffPeriodicTrainingUpdateRequest,
  type StaffServiceQualificationCloseRequest,
  type StaffServiceQualificationCreateRequest,
  type StaffServiceQualificationInvalidateRequest,
  type StaffServiceQualificationReplacementRequest,
  type StaffServiceQualificationResponse,
  type TrainingCourseResponse,
} from '../services/staffApi';
import { evaluateContinuingEducation } from '../components/staff/continuingEducation';
import '../styles/staff.css';

function formValue(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === 'string' ? value.trim() : '';
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '요청을 처리하지 못했습니다.';
}

function healthQueryErrorMessage(error: unknown): string {
  if (error instanceof HealthApiError) {
    if (error.status === 403) return '검진 정보를 조회할 권한이 없습니다.';
    if (error.status === 409) return '최신 검진 상태를 다시 확인해주세요.';
    if (error.status === 422) return '검진 조회 조건을 확인해주세요.';
  }
  return '검진 정보를 불러오지 못했습니다.';
}

function consultationQueryErrorMessage(error: unknown): string {
  if (error instanceof ConsultationApiError) {
    if (error.status === 403) return '분기상담을 조회할 권한이 없습니다.';
    if (error.status === 409) return '최신 분기상담 상태를 다시 확인해주세요.';
    if (error.status === 422) return '분기상담 조회 조건을 확인해주세요.';
  }
  return '분기상담 정보를 불러오지 못했습니다.';
}

function consultationMutationErrorMessage(error: unknown): string {
  if (error instanceof ConsultationApiError) {
    if (error.status === 403) return '분기상담을 변경할 권한이 없습니다.';
    if (error.status === 409) return '최신 분기상담 상태를 다시 확인해주세요.';
    if (error.status === 422) return '입력값을 확인해주세요.';
  }
  return '분기상담 요청을 처리하지 못했습니다.';
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof Error && error.name === 'AbortError') ||
    (typeof DOMException !== 'undefined' &&
      error instanceof DOMException &&
      error.name === 'AbortError')
  );
}

function staleStaffMutationError(): Error {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('Staff mutation session changed', 'AbortError');
  }
  const error = new Error('Staff mutation session changed');
  error.name = 'AbortError';
  return error;
}

function staffIdFromLocation(): number | null {
  if (typeof window === 'undefined') return null;
  const raw = new URLSearchParams(window.location.search).get('staff_id');
  if (!raw) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

type AbortControllerRef = { current: AbortController | null };

function beginAbortableRequest(ref: AbortControllerRef): AbortController {
  ref.current?.abort();
  const controller = new AbortController();
  ref.current = controller;
  return controller;
}

function finishAbortableRequest(ref: AbortControllerRef, controller: AbortController): void {
  if (ref.current === controller) {
    ref.current = null;
  }
}

const STAFF_MUTATION_ROOTS = new Set(['staff-create', 'staff-close-employment', 'staff-rehire']);
const VS4_HEALTH_QUERY_ROOTS = new Set([
  'staff-health-checks',
  'staff-health-check-requirements',
]);
const VS4_HEALTH_MUTATION_ROOTS = new Set([
  'staff-health-fact-create',
  'staff-health-fact-update',
  'staff-health-fact-invalidate',
  'staff-health-requirement-update',
  'staff-health-requirement-invalidate',
]);
const VS5_CONSULTATION_QUERY_ROOTS = new Set(['staff-quarterly-consultations']);
const VS5_CONSULTATION_MUTATION_ROOTS = new Set([
  'staff-quarterly-consultation-create',
  'staff-quarterly-consultation-update',
  'staff-quarterly-consultation-invalidate',
]);

type StaffDetailTab =
  | 'overview'
  | 'licenses'
  | 'qualifications'
  | 'training'
  | 'health'
  | 'consultation';

type LicenseFormState = {
  replacement: StaffLicenseResponse | null;
  open: boolean;
};

type QualificationFormState = {
  replacement: StaffServiceQualificationResponse | null;
  open: boolean;
};

type HealthFactFormState = {
  open: boolean;
  editing: StaffHealthCheckResponse | null;
  checkDate: string;
  employmentId: string;
  checkTypeCode: string;
  resultNote: string;
};

type HealthRequirementDraft = {
  status: HealthCheckRequirementStatus;
  healthCheckId: string;
  exemptReasonText: string;
};

type HealthMutationContext = {
  staffId: number;
  sessionEpoch: number;
  staffSelectionEpoch: number;
};

type QuarterlyConsultationFormState = {
  mode: 'create' | 'edit' | 'replace' | null;
  editing: StaffQuarterlyConsultationResponse | null;
  calendarYear: string;
  quarterNo: string;
  status: QuarterlyConsultationStatus;
  counselingDate: string;
  content: string;
  incompleteReasonText: string;
  exemptReasonText: string;
};

type ConsultationMutationContext = {
  staffId: number;
  sessionEpoch: number;
  staffSelectionEpoch: number;
};

function emptyHealthFactForm(): HealthFactFormState {
  return {
    open: false,
    editing: null,
    checkDate: '',
    employmentId: '',
    checkTypeCode: '',
    resultNote: '',
  };
}

function emptyQuarterlyConsultationForm(): QuarterlyConsultationFormState {
  return {
    mode: null,
    editing: null,
    calendarYear: String(new Date().getFullYear()),
    quarterNo: '1',
    status: 'COMPLETE',
    counselingDate: '',
    content: '',
    incompleteReasonText: '',
    exemptReasonText: '',
  };
}

function clearHealthMutationCache(queryClient: QueryClient, staffId?: number): void {
  for (const mutation of queryClient.getMutationCache().getAll()) {
    const root = mutation.options.mutationKey?.[0];
    if (typeof root !== 'string' || !VS4_HEALTH_MUTATION_ROOTS.has(root)) continue;
    if (staffId !== undefined) {
      const variables = mutation.state.variables;
      if (
        !variables ||
        typeof variables !== 'object' ||
        (variables as { staffId?: unknown }).staffId !== staffId
      ) {
        continue;
      }
    }
    queryClient.getMutationCache().remove(mutation);
  }
}

function clearHealthCache(queryClient: QueryClient, staffId?: number): void {
  for (const query of queryClient.getQueryCache().getAll()) {
    const root = query.queryKey[0];
    if (
      typeof root !== 'string' ||
      !VS4_HEALTH_QUERY_ROOTS.has(root) ||
      (staffId !== undefined && query.queryKey[1] !== staffId)
    ) {
      continue;
    }
    void queryClient.cancelQueries({ queryKey: query.queryKey, exact: true });
    queryClient.removeQueries({ queryKey: query.queryKey, exact: true });
  }
  clearHealthMutationCache(queryClient, staffId);
}

function clearConsultationMutationCache(queryClient: QueryClient, staffId?: number): void {
  for (const mutation of queryClient.getMutationCache().getAll()) {
    const root = mutation.options.mutationKey?.[0];
    if (typeof root !== 'string' || !VS5_CONSULTATION_MUTATION_ROOTS.has(root)) continue;
    if (staffId !== undefined) {
      const variables = mutation.state.variables;
      if (
        !variables ||
        typeof variables !== 'object' ||
        (variables as { staffId?: unknown }).staffId !== staffId
      ) {
        continue;
      }
    }
    queryClient.getMutationCache().remove(mutation);
  }
}

function clearConsultationCache(queryClient: QueryClient, staffId?: number): void {
  for (const query of queryClient.getQueryCache().getAll()) {
    const root = query.queryKey[0];
    if (
      typeof root !== 'string' ||
      !VS5_CONSULTATION_QUERY_ROOTS.has(root) ||
      (staffId !== undefined && query.queryKey[1] !== staffId)
    ) {
      continue;
    }
    void queryClient.cancelQueries({ queryKey: query.queryKey, exact: true });
    queryClient.removeQueries({ queryKey: query.queryKey, exact: true });
  }
  clearConsultationMutationCache(queryClient, staffId);
}

const VS2_MUTATION_ROOTS = new Set([
  'staff-license-create',
  'staff-license-replace',
  'staff-license-invalidate',
  'staff-qualification-create',
  'staff-qualification-replace',
  'staff-qualification-close',
  'staff-qualification-invalidate',
]);

const VS3_MUTATION_ROOTS = new Set([
  'staff-training-onboarding-update',
  'staff-training-periodic-create',
  'staff-training-periodic-update',
  'staff-training-periodic-invalidate',
]);

type TrainingCycleType = TrainingCourseResponse['cycle_type'];

function cycleLabel(cycleType: TrainingCycleType): string {
  if (cycleType === 'ON_HIRE') return '신규직원교육';
  if (cycleType === 'HALF_YEAR') return '반기교육';
  if (cycleType === 'BIENNIAL') return '2년 주기';
  return '연간교육';
}

function currentTrainingPeriodKey(cycleType: Exclude<TrainingCycleType, 'ON_HIRE'>): string {
  const year = new Date().getFullYear();
  if (cycleType === 'ANNUAL' || cycleType === 'BIENNIAL') return String(year);
  return `${year}-${new Date().getMonth() < 6 ? 'H1' : 'H2'}`;
}

function trainingPeriodOptions(cycleType: Exclude<TrainingCycleType, 'ON_HIRE'>): string[] {
  const year = new Date().getFullYear();
  if (cycleType === 'ANNUAL' || cycleType === 'BIENNIAL') {
    return [String(year - 1), String(year), String(year + 1)];
  }
  return [
    `${year - 1}-H2`,
    `${year}-H1`,
    `${year}-H2`,
    `${year + 1}-H1`,
  ];
}

type TrainingMutationContext = {
  sessionEpoch: number;
  staffSelectionEpoch: number;
  staffId: number;
};

export const StaffPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('name');
  const [page, setPage] = useState(1);
  const [listScrollTop, setListScrollTop] = useState(0);
  const [selectedStaffId, setSelectedStaffId] = useState<number | null>(staffIdFromLocation);
  const [selectedTab, setSelectedTab] = useState<StaffDetailTab>('overview');
  const [halfYearTrainingPeriod, setHalfYearTrainingPeriod] = useState(() =>
    currentTrainingPeriodKey('HALF_YEAR'),
  );
  const [annualTrainingPeriod, setAnnualTrainingPeriod] = useState(() =>
    currentTrainingPeriodKey('ANNUAL'),
  );
  const [biennialTrainingPeriod, setBiennialTrainingPeriod] = useState(() =>
    currentTrainingPeriodKey('BIENNIAL'),
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const [rehireOpen, setRehireOpen] = useState(false);
  const [licenseForm, setLicenseForm] = useState<LicenseFormState>({
    open: false,
    replacement: null,
  });
  const [qualificationForm, setQualificationForm] = useState<QualificationFormState>({
    open: false,
    replacement: null,
  });
  const [qualificationCloseTarget, setQualificationCloseTarget] =
    useState<StaffServiceQualificationResponse | null>(null);
  const [healthFactForm, setHealthFactForm] = useState<HealthFactFormState>(
    emptyHealthFactForm,
  );
  const [healthRequirementDrafts, setHealthRequirementDrafts] = useState<
    Record<number, HealthRequirementDraft>
  >({});
  const [healthFactInvalidateTarget, setHealthFactInvalidateTarget] =
    useState<StaffHealthCheckResponse | null>(null);
  const [healthRequirementInvalidateTarget, setHealthRequirementInvalidateTarget] =
    useState<StaffHealthCheckRequirementResponse | null>(null);
  const [healthFieldErrors, setHealthFieldErrors] = useState<Record<string, string>>({});
  const [quarterlyConsultationForm, setQuarterlyConsultationForm] =
    useState<QuarterlyConsultationFormState>(emptyQuarterlyConsultationForm);
  const [quarterlyConsultationInvalidateTarget, setQuarterlyConsultationInvalidateTarget] =
    useState<StaffQuarterlyConsultationResponse | null>(null);
  const [consultationFieldErrors, setConsultationFieldErrors] = useState<
    Record<string, string>
  >({});
  const [revealOpen, setRevealOpen] = useState(false);
  const [currentPin, setCurrentPin] = useState('');
  const [revealedResidentNumber, setRevealedResidentNumber] = useState<string | null>(
    null,
  );
  const [isRevealPending, setIsRevealPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [sessionReady, setSessionReady] = useState(true);
  const revealAbortRef = useRef<AbortController | null>(null);
  const revealRequestIdRef = useRef(0);
  const sessionEpochRef = useRef(0);
  const selectedStaffIdRef = useRef<number | null>(staffIdFromLocation());
  const trainingSelectionEpochRef = useRef(0);
  const healthSelectionEpochRef = useRef(0);
  const consultationSelectionEpochRef = useRef(0);
  const createAbortRef = useRef<AbortController | null>(null);
  const closeAbortRef = useRef<AbortController | null>(null);
  const rehireAbortRef = useRef<AbortController | null>(null);
  const licenseMutationAbortRef = useRef<AbortController | null>(null);
  const qualificationMutationAbortRef = useRef<AbortController | null>(null);
  const trainingMutationAbortRef = useRef<AbortController | null>(null);
  const healthFactMutationAbortRef = useRef<AbortController | null>(null);
  const healthRequirementMutationAbortRef = useRef<AbortController | null>(null);
  const consultationMutationAbortRef = useRef<AbortController | null>(null);
  const createPayloadRef = useRef<StaffCreateRequest | null>(null);
  const listScrollRef = useRef<HTMLDivElement | null>(null);

  const changeStaffSelection = useCallback((staffId: number | null) => {
    if (selectedStaffIdRef.current !== staffId) {
      const previousStaffId = selectedStaffIdRef.current;
      selectedStaffIdRef.current = staffId;
      trainingSelectionEpochRef.current += 1;
      healthSelectionEpochRef.current += 1;
      consultationSelectionEpochRef.current += 1;
      trainingMutationAbortRef.current?.abort();
      trainingMutationAbortRef.current = null;
      healthFactMutationAbortRef.current?.abort();
      healthFactMutationAbortRef.current = null;
      healthRequirementMutationAbortRef.current?.abort();
      healthRequirementMutationAbortRef.current = null;
      consultationMutationAbortRef.current?.abort();
      consultationMutationAbortRef.current = null;
      void queryClient.cancelQueries({ queryKey: ['staff-onboarding-trainings'] });
      void queryClient.cancelQueries({ queryKey: ['staff-periodic-trainings'] });
      clearHealthCache(queryClient, previousStaffId ?? undefined);
      clearConsultationCache(queryClient, previousStaffId ?? undefined);
      setHealthFactForm(emptyHealthFactForm());
      setHealthRequirementDrafts({});
      setHealthFactInvalidateTarget(null);
      setHealthRequirementInvalidateTarget(null);
      setHealthFieldErrors({});
      setQuarterlyConsultationForm(emptyQuarterlyConsultationForm());
      setQuarterlyConsultationInvalidateTarget(null);
      setConsultationFieldErrors({});
      setActionError(null);
    }
    setSelectedStaffId(staffId);
  }, [queryClient]);

  const capabilitiesQuery = useQuery({
    queryKey: ['staff-capabilities'],
    queryFn: ({ signal }) => fetchSessionCapabilities(signal),
    enabled: sessionReady,
    staleTime: 0,
    gcTime: 0,
  });
  const licenseTypesQuery = useQuery({
    queryKey: ['staff-license-types'],
    queryFn: ({ signal }) => fetchLicenseTypes(signal),
    enabled: sessionReady,
    staleTime: 5 * 60 * 1000,
  });
  const serviceCatalogQuery = useQuery({
    queryKey: ['staff-service-catalog'],
    queryFn: ({ signal }) => fetchServiceCatalog(signal),
    enabled: sessionReady,
    staleTime: 5 * 60 * 1000,
  });
  const listQuery = useQuery({
    queryKey: ['staff-list', search, page],
    queryFn: ({ signal }) => fetchStaffList(search, signal, page),
    enabled: sessionReady,
  });
  const detailQuery = useQuery({
    queryKey: ['staff-detail', selectedStaffId],
    queryFn: ({ signal }) => fetchStaffDetail(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null,
  });
  const healthFactsQuery = useQuery({
    queryKey: ['staff-health-checks', selectedStaffId],
    queryFn: ({ signal }) => fetchStaffHealthChecks(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null && selectedTab === 'health',
  });
  const healthRequirementsQuery = useQuery({
    queryKey: ['staff-health-check-requirements', selectedStaffId],
    queryFn: ({ signal }) =>
      fetchStaffHealthCheckRequirements(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null && selectedTab === 'health',
  });
  const quarterlyConsultationsQuery = useQuery({
    queryKey: ['staff-quarterly-consultations', selectedStaffId],
    queryFn: ({ signal }) =>
      fetchStaffQuarterlyConsultations(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null,
  });
  const licensesQuery = useQuery({
    queryKey: ['staff-licenses', selectedStaffId],
    queryFn: ({ signal }) => fetchStaffLicenses(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null,
  });
  const qualificationsQuery = useQuery({
    queryKey: ['staff-qualifications', selectedStaffId],
    queryFn: ({ signal }) => fetchStaffServiceQualifications(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null,
  });
  const trainingCoursesQuery = useQuery({
    queryKey: ['staff-training-courses'],
    queryFn: ({ signal }) => fetchTrainingCourses(signal),
    enabled: sessionReady,
    staleTime: 5 * 60 * 1000,
  });
  const onboardingTrainingsQuery = useQuery({
    queryKey: ['staff-onboarding-trainings', selectedStaffId],
    queryFn: ({ signal }) => fetchStaffOnboardingTrainings(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null,
  });
  const periodicTrainingsQuery = useQuery({
    queryKey: ['staff-periodic-trainings', selectedStaffId],
    queryFn: ({ signal }) => fetchStaffPeriodicTrainings(selectedStaffId as number, signal),
    enabled: sessionReady && selectedStaffId !== null,
  });

  useEffect(() => {
    const items = listQuery.data?.items ?? [];
    const locationStaffId = staffIdFromLocation();
    if (locationStaffId !== null) {
      if (selectedStaffId !== locationStaffId) {
        changeStaffSelection(locationStaffId);
      }
      return;
    }
    if (items.length === 0) {
      changeStaffSelection(null);
      return;
    }
    if (selectedStaffId === null || !items.some((item) => item.id === selectedStaffId)) {
      changeStaffSelection(items[0].id);
    }
  }, [changeStaffSelection, listQuery.data, selectedStaffId]);

  useEffect(() => {
    if (listScrollRef.current) {
      listScrollRef.current.scrollTop = listScrollTop;
    }
  }, [listScrollTop]);

  useEffect(() => {
    setLicenseForm({ open: false, replacement: null });
    setQualificationForm({ open: false, replacement: null });
    setQualificationCloseTarget(null);
  }, [selectedStaffId]);

  useEffect(() => {
    const items = healthRequirementsQuery.data?.items ?? [];
    setHealthRequirementDrafts(
      Object.fromEntries(
        items
          .filter((item) => item.invalidated_at_utc == null)
          .map((item) => [
            item.id,
            {
              status: item.status,
              healthCheckId: item.health_check_id === null ? '' : String(item.health_check_id),
              exemptReasonText: item.exempt_reason_text ?? '',
            } satisfies HealthRequirementDraft,
          ]),
      ),
    );
  }, [healthRequirementsQuery.data?.items]);

  useEffect(() => {
    const restoreStaffFromHistory = () => {
      const staffId = staffIdFromLocation();
      if (staffId !== null) {
        changeStaffSelection(staffId);
      }
    };
    window.addEventListener('popstate', restoreStaffFromHistory);
    return () => window.removeEventListener('popstate', restoreStaffFromHistory);
  }, [changeStaffSelection]);

  useEffect(() => {
    const refreshCapabilities = () => {
      void capabilitiesQuery.refetch();
    };
    window.addEventListener('focus', refreshCapabilities);
    return () => window.removeEventListener('focus', refreshCapabilities);
  }, [capabilitiesQuery]);

  const invalidateStaff = async (staffId?: number) => {
    const invalidations = [queryClient.invalidateQueries({ queryKey: ['staff-list'] })];
    if (staffId !== undefined) {
      invalidations.push(
        queryClient.invalidateQueries({ queryKey: ['staff-detail', staffId] }),
        queryClient.invalidateQueries({ queryKey: ['staff-health-checks', staffId] }),
        queryClient.invalidateQueries({
          queryKey: ['staff-health-check-requirements', staffId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['staff-quarterly-consultations', staffId],
        }),
        queryClient.invalidateQueries({ queryKey: ['staff-licenses', staffId] }),
        queryClient.invalidateQueries({ queryKey: ['staff-qualifications', staffId] }),
        queryClient.invalidateQueries({ queryKey: ['staff-onboarding-trainings', staffId] }),
        queryClient.invalidateQueries({ queryKey: ['staff-periodic-trainings', staffId] }),
      );
    }
    await Promise.all(invalidations);
  };

  const handleMutationError = (error: unknown) => {
    if (isAbortError(error)) return;
    setActionError(errorMessage(error));
    if (error instanceof ApiError && error.status === 403) {
      void capabilitiesQuery.refetch();
    }
  };

  const handleHealthMutationError = (error: unknown) => {
    if (isAbortError(error)) return;
    const fieldErrors =
      error instanceof HealthApiError
        ? Object.fromEntries(error.fieldErrors.map((item) => [item.field, item.message]))
        : {};
    setHealthFieldErrors(fieldErrors);
    setActionError(
      error instanceof HealthApiError
        ? error.message
        : '검진 요청을 처리하지 못했습니다.',
    );
    if (error instanceof HealthApiError && error.status === 403) {
      void capabilitiesQuery.refetch();
    }
    clearHealthMutationCache(queryClient);
  };

  const handleConsultationMutationError = (error: unknown) => {
    if (isAbortError(error)) return;
    const fieldErrors =
      error instanceof ConsultationApiError
        ? Object.fromEntries(error.fieldErrors.map((item) => [item.field, item.message]))
        : {};
    setConsultationFieldErrors(fieldErrors);
    setActionError(consultationMutationErrorMessage(error));
    if (error instanceof ConsultationApiError && error.status === 403) {
      void capabilitiesQuery.refetch();
    }
    clearConsultationMutationCache(queryClient);
  };

  const createMutation = useMutation({
    mutationKey: ['staff-create'],
    mutationFn: async ({ sessionEpoch }: { sessionEpoch: number }) => {
      const payload = createPayloadRef.current;
      if (!payload) throw staleStaffMutationError();
      const controller = beginAbortableRequest(createAbortRef);
      try {
        const data = await createStaff(payload, controller.signal);
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(createAbortRef, controller);
      }
    },
    onSuccess: async (result) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setCreateOpen(false);
      setActionError(null);
      await invalidateStaff();
      if (result.sessionEpoch === sessionEpochRef.current) {
        setSelectedStaffId(result.data.id);
      }
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
    onSettled: (_data, _error, variables) => {
      if (variables.sessionEpoch === sessionEpochRef.current) {
        createPayloadRef.current = null;
      }
    },
  });
  const closeMutation = useMutation({
    mutationKey: ['staff-close-employment'],
    mutationFn: async ({
      staffId,
      employmentId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      employmentId: number;
      payload: StaffEmploymentCloseRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(closeAbortRef);
      try {
        const data = await closeEmployment(staffId, employmentId, payload, controller.signal);
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(closeAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setCloseOpen(false);
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const rehireMutation = useMutation({
    mutationKey: ['staff-rehire'],
    mutationFn: ({
      staffId,
      expectedStaffRowVersion,
      startDate,
      sessionEpoch,
    }: {
      staffId: number;
      expectedStaffRowVersion: number;
      startDate: string;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(rehireAbortRef);
      return createEmployment(
        staffId,
        {
          expected_staff_row_version: expectedStaffRowVersion,
          start_date: startDate,
        },
        controller.signal,
      )
        .then((data) => ({ data, sessionEpoch }))
        .finally(() => finishAbortableRequest(rehireAbortRef, controller));
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setRehireOpen(false);
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const licenseCreateMutation = useMutation({
    mutationKey: ['staff-license-create'],
    mutationFn: async ({
      staffId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      payload: StaffLicenseCreateRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(licenseMutationAbortRef);
      try {
        const data = await createStaffLicense(staffId, payload, controller.signal);
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(licenseMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setLicenseForm({ open: false, replacement: null });
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const licenseReplacementMutation = useMutation({
    mutationKey: ['staff-license-replace'],
    mutationFn: async ({
      staffId,
      licenseId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      licenseId: number;
      payload: StaffLicenseReplacementRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(licenseMutationAbortRef);
      try {
        const data = await replaceStaffLicense(staffId, licenseId, payload, controller.signal);
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(licenseMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setLicenseForm({ open: false, replacement: null });
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const licenseInvalidateMutation = useMutation({
    mutationKey: ['staff-license-invalidate'],
    mutationFn: async ({
      staffId,
      licenseId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      licenseId: number;
      payload: StaffLicenseInvalidateRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(licenseMutationAbortRef);
      try {
        const data = await invalidateStaffLicense(staffId, licenseId, payload, controller.signal);
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(licenseMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const qualificationCreateMutation = useMutation({
    mutationKey: ['staff-qualification-create'],
    mutationFn: async ({
      staffId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      payload: StaffServiceQualificationCreateRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(qualificationMutationAbortRef);
      try {
        const data = await createStaffServiceQualification(staffId, payload, controller.signal);
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(qualificationMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setQualificationForm({ open: false, replacement: null });
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const qualificationReplacementMutation = useMutation({
    mutationKey: ['staff-qualification-replace'],
    mutationFn: async ({
      staffId,
      qualificationId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      qualificationId: number;
      payload: StaffServiceQualificationReplacementRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(qualificationMutationAbortRef);
      try {
        const data = await replaceStaffServiceQualification(
          staffId,
          qualificationId,
          payload,
          controller.signal,
        );
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(qualificationMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setQualificationForm({ open: false, replacement: null });
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const qualificationCloseMutation = useMutation({
    mutationKey: ['staff-qualification-close'],
    mutationFn: async ({
      staffId,
      qualificationId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      qualificationId: number;
      payload: StaffServiceQualificationCloseRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(qualificationMutationAbortRef);
      try {
        const data = await closeStaffServiceQualification(
          staffId,
          qualificationId,
          payload,
          controller.signal,
        );
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(qualificationMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setQualificationCloseTarget(null);
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const qualificationInvalidateMutation = useMutation({
    mutationKey: ['staff-qualification-invalidate'],
    mutationFn: async ({
      staffId,
      qualificationId,
      payload,
      sessionEpoch,
    }: {
      staffId: number;
      qualificationId: number;
      payload: StaffServiceQualificationInvalidateRequest;
      sessionEpoch: number;
    }) => {
      const controller = beginAbortableRequest(qualificationMutationAbortRef);
      try {
        const data = await invalidateStaffServiceQualification(
          staffId,
          qualificationId,
          payload,
          controller.signal,
        );
        return { data, sessionEpoch };
      } finally {
        finishAbortableRequest(qualificationMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (result.sessionEpoch !== sessionEpochRef.current) return;
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables.sessionEpoch !== sessionEpochRef.current) return;
      handleMutationError(error);
    },
  });
  const isCurrentHealthContext = (context: HealthMutationContext): boolean =>
    context.sessionEpoch === sessionEpochRef.current &&
    context.staffSelectionEpoch === healthSelectionEpochRef.current &&
    context.staffId === selectedStaffIdRef.current;

  const healthFactCreateMutation = useMutation({
    mutationKey: ['staff-health-fact-create'],
    mutationFn: async ({
      staffId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: HealthMutationContext & { payload: StaffHealthCheckCreateRequest }) => {
      const controller = beginAbortableRequest(healthFactMutationAbortRef);
      try {
        const data = await createStaffHealthCheck(staffId, payload, controller.signal);
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(healthFactMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentHealthContext(result)) return;
      setHealthFactForm(emptyHealthFactForm());
      setHealthFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentHealthContext(variables)) handleHealthMutationError(error);
    },
    onSettled: () => clearHealthMutationCache(queryClient),
  });

  const healthFactUpdateMutation = useMutation({
    mutationKey: ['staff-health-fact-update'],
    mutationFn: async ({
      staffId,
      healthCheckId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: HealthMutationContext & {
      healthCheckId: number;
      payload: StaffHealthCheckUpdateRequest;
    }) => {
      const controller = beginAbortableRequest(healthFactMutationAbortRef);
      try {
        const data = await updateStaffHealthCheck(
          staffId,
          healthCheckId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(healthFactMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentHealthContext(result)) return;
      setHealthFactForm(emptyHealthFactForm());
      setHealthFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentHealthContext(variables)) handleHealthMutationError(error);
    },
    onSettled: () => clearHealthMutationCache(queryClient),
  });

  const healthFactInvalidateMutation = useMutation({
    mutationKey: ['staff-health-fact-invalidate'],
    mutationFn: async ({
      staffId,
      healthCheckId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: HealthMutationContext & {
      healthCheckId: number;
      payload: Pick<StaffHealthCheckUpdateRequest, 'expected_row_version'>;
    }) => {
      const controller = beginAbortableRequest(healthFactMutationAbortRef);
      try {
        const data = await invalidateStaffHealthCheck(
          staffId,
          healthCheckId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(healthFactMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentHealthContext(result)) return;
      setHealthFactInvalidateTarget(null);
      setHealthFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentHealthContext(variables)) {
        handleHealthMutationError(error);
        void queryClient.refetchQueries({
          queryKey: ['staff-health-checks', variables.staffId],
          type: 'active',
        });
      }
    },
    onSettled: () => clearHealthMutationCache(queryClient),
  });

  const healthRequirementUpdateMutation = useMutation({
    mutationKey: ['staff-health-requirement-update'],
    mutationFn: async ({
      staffId,
      requirementId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: HealthMutationContext & {
      requirementId: number;
      payload: StaffHealthCheckRequirementUpdateRequest;
    }) => {
      const controller = beginAbortableRequest(healthRequirementMutationAbortRef);
      try {
        const data = await updateStaffHealthCheckRequirement(
          staffId,
          requirementId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(healthRequirementMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentHealthContext(result)) return;
      setHealthFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentHealthContext(variables)) handleHealthMutationError(error);
    },
    onSettled: () => clearHealthMutationCache(queryClient),
  });

  const healthRequirementInvalidateMutation = useMutation({
    mutationKey: ['staff-health-requirement-invalidate'],
    mutationFn: async ({
      staffId,
      requirementId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: HealthMutationContext & {
      requirementId: number;
      payload: Pick<StaffHealthCheckRequirementUpdateRequest, 'expected_row_version'>;
    }) => {
      const controller = beginAbortableRequest(healthRequirementMutationAbortRef);
      try {
        const data = await invalidateStaffHealthCheckRequirement(
          staffId,
          requirementId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(healthRequirementMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentHealthContext(result)) return;
      setHealthRequirementInvalidateTarget(null);
      setHealthFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentHealthContext(variables)) handleHealthMutationError(error);
    },
    onSettled: () => clearHealthMutationCache(queryClient),
  });

  const isCurrentConsultationContext = (context: ConsultationMutationContext): boolean =>
    context.sessionEpoch === sessionEpochRef.current &&
    context.staffSelectionEpoch === consultationSelectionEpochRef.current &&
    context.staffId === selectedStaffIdRef.current;

  const consultationCreateMutation = useMutation({
    mutationKey: ['staff-quarterly-consultation-create'],
    mutationFn: async ({
      staffId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: ConsultationMutationContext & {
      payload: StaffQuarterlyConsultationCreateRequest;
    }) => {
      const controller = beginAbortableRequest(consultationMutationAbortRef);
      try {
        const data = await createStaffQuarterlyConsultation(
          staffId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(consultationMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentConsultationContext(result)) return;
      setQuarterlyConsultationForm(emptyQuarterlyConsultationForm());
      setConsultationFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentConsultationContext(variables)) {
        handleConsultationMutationError(error);
      }
    },
    onSettled: () => clearConsultationMutationCache(queryClient),
  });

  const consultationUpdateMutation = useMutation({
    mutationKey: ['staff-quarterly-consultation-update'],
    mutationFn: async ({
      staffId,
      consultationId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: ConsultationMutationContext & {
      consultationId: number;
      payload: StaffQuarterlyConsultationUpdateRequest;
    }) => {
      const controller = beginAbortableRequest(consultationMutationAbortRef);
      try {
        const data = await updateStaffQuarterlyConsultation(
          staffId,
          consultationId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(consultationMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentConsultationContext(result)) return;
      setQuarterlyConsultationForm(emptyQuarterlyConsultationForm());
      setConsultationFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentConsultationContext(variables)) {
        handleConsultationMutationError(error);
      }
    },
    onSettled: () => clearConsultationMutationCache(queryClient),
  });

  const consultationInvalidateMutation = useMutation({
    mutationKey: ['staff-quarterly-consultation-invalidate'],
    mutationFn: async ({
      staffId,
      consultationId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: ConsultationMutationContext & {
      consultationId: number;
      payload: StaffQuarterlyConsultationReplaceRequest;
    }) => {
      const controller = beginAbortableRequest(consultationMutationAbortRef);
      try {
        const data = await invalidateStaffQuarterlyConsultation(
          staffId,
          consultationId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(consultationMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentConsultationContext(result)) return;
      setQuarterlyConsultationInvalidateTarget(null);
      setQuarterlyConsultationForm(emptyQuarterlyConsultationForm());
      setConsultationFieldErrors({});
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (variables && isCurrentConsultationContext(variables)) {
        handleConsultationMutationError(error);
      }
    },
    onSettled: () => clearConsultationMutationCache(queryClient),
  });

  const isCurrentTrainingContext = (context: TrainingMutationContext): boolean =>
    context.sessionEpoch === sessionEpochRef.current &&
    context.staffSelectionEpoch === trainingSelectionEpochRef.current &&
    context.staffId === selectedStaffIdRef.current;

  const onboardingUpdateMutation = useMutation({
    mutationKey: ['staff-training-onboarding-update'],
    mutationFn: async ({
      staffId,
      trainingId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: TrainingMutationContext & {
      trainingId: number;
      payload: StaffOnboardingTrainingUpdateRequest;
    }) => {
      const controller = beginAbortableRequest(trainingMutationAbortRef);
      try {
        const data = await updateStaffOnboardingTraining(
          staffId,
          trainingId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(trainingMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentTrainingContext(result)) return;
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (!variables || !isCurrentTrainingContext(variables)) return;
      handleMutationError(error);
    },
  });

  const periodicCreateMutation = useMutation({
    mutationKey: ['staff-training-periodic-create'],
    mutationFn: async ({
      staffId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: TrainingMutationContext & { payload: StaffPeriodicTrainingCreateRequest }) => {
      const controller = beginAbortableRequest(trainingMutationAbortRef);
      try {
        const data = await createStaffPeriodicTraining(staffId, payload, controller.signal);
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(trainingMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentTrainingContext(result)) return;
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (!variables || !isCurrentTrainingContext(variables)) return;
      handleMutationError(error);
    },
  });

  const periodicUpdateMutation = useMutation({
    mutationKey: ['staff-training-periodic-update'],
    mutationFn: async ({
      staffId,
      trainingId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: TrainingMutationContext & {
      trainingId: number;
      payload: StaffPeriodicTrainingUpdateRequest;
    }) => {
      const controller = beginAbortableRequest(trainingMutationAbortRef);
      try {
        const data = await updateStaffPeriodicTraining(
          staffId,
          trainingId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(trainingMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentTrainingContext(result)) return;
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (!variables || !isCurrentTrainingContext(variables)) return;
      handleMutationError(error);
    },
  });

  const periodicInvalidateMutation = useMutation({
    mutationKey: ['staff-training-periodic-invalidate'],
    mutationFn: async ({
      staffId,
      trainingId,
      payload,
      sessionEpoch,
      staffSelectionEpoch,
    }: TrainingMutationContext & {
      trainingId: number;
      payload: StaffPeriodicTrainingInvalidateRequest;
    }) => {
      const controller = beginAbortableRequest(trainingMutationAbortRef);
      try {
        const data = await invalidateStaffPeriodicTraining(
          staffId,
          trainingId,
          payload,
          controller.signal,
        );
        return { data, staffId, sessionEpoch, staffSelectionEpoch };
      } finally {
        finishAbortableRequest(trainingMutationAbortRef, controller);
      }
    },
    onSuccess: async (result, variables) => {
      if (!isCurrentTrainingContext(result)) return;
      setActionError(null);
      await invalidateStaff(variables.staffId);
    },
    onError: (error, variables) => {
      if (!variables || !isCurrentTrainingContext(variables)) return;
      handleMutationError(error);
    },
  });

  const trainingMutationPending =
    onboardingUpdateMutation.isPending ||
    periodicCreateMutation.isPending ||
    periodicUpdateMutation.isPending ||
    periodicInvalidateMutation.isPending;
  const healthMutationPending =
    healthFactCreateMutation.isPending ||
    healthFactUpdateMutation.isPending ||
    healthFactInvalidateMutation.isPending ||
    healthRequirementUpdateMutation.isPending ||
    healthRequirementInvalidateMutation.isPending;
  const consultationMutationPending =
    consultationCreateMutation.isPending ||
    consultationUpdateMutation.isPending ||
    consultationInvalidateMutation.isPending;

  const purgeStaffSessionData = useCallback(() => {
    sessionEpochRef.current += 1;
    revealRequestIdRef.current += 1;
    revealAbortRef.current?.abort();
    revealAbortRef.current = null;
    createAbortRef.current?.abort();
    createAbortRef.current = null;
    closeAbortRef.current?.abort();
    closeAbortRef.current = null;
    rehireAbortRef.current?.abort();
    rehireAbortRef.current = null;
    licenseMutationAbortRef.current?.abort();
    licenseMutationAbortRef.current = null;
    qualificationMutationAbortRef.current?.abort();
    qualificationMutationAbortRef.current = null;
    trainingMutationAbortRef.current?.abort();
    trainingMutationAbortRef.current = null;
    healthFactMutationAbortRef.current?.abort();
    healthFactMutationAbortRef.current = null;
    healthRequirementMutationAbortRef.current?.abort();
    healthRequirementMutationAbortRef.current = null;
    consultationMutationAbortRef.current?.abort();
    consultationMutationAbortRef.current = null;
    trainingSelectionEpochRef.current += 1;
    healthSelectionEpochRef.current += 1;
    consultationSelectionEpochRef.current += 1;
    selectedStaffIdRef.current = null;
    createPayloadRef.current = null;
    void queryClient.cancelQueries({
      predicate: (query) => {
        const root = query.queryKey[0];
        return (
          root === 'staff-list' ||
          root === 'staff-detail' ||
          root === 'staff-capabilities' ||
          root === 'staff-license-types' ||
          root === 'staff-service-catalog' ||
          root === 'staff-licenses' ||
          root === 'staff-qualifications' ||
          root === 'staff-training-courses' ||
          root === 'staff-onboarding-trainings' ||
          root === 'staff-periodic-trainings' ||
          VS4_HEALTH_QUERY_ROOTS.has(String(root)) ||
          VS5_CONSULTATION_QUERY_ROOTS.has(String(root))
        );
      },
    });
    queryClient.removeQueries({
      predicate: (query) => {
        const root = query.queryKey[0];
        return (
          root === 'staff-list' ||
          root === 'staff-detail' ||
          root === 'staff-capabilities' ||
          root === 'staff-license-types' ||
          root === 'staff-service-catalog' ||
          root === 'staff-licenses' ||
          root === 'staff-qualifications' ||
          root === 'staff-training-courses' ||
          root === 'staff-onboarding-trainings' ||
          root === 'staff-periodic-trainings' ||
          VS4_HEALTH_QUERY_ROOTS.has(String(root)) ||
          VS5_CONSULTATION_QUERY_ROOTS.has(String(root))
        );
      },
    });
    for (const mutation of queryClient.getMutationCache().getAll()) {
      const root = mutation.options.mutationKey?.[0];
      if (
        typeof root === 'string' &&
        (STAFF_MUTATION_ROOTS.has(root) ||
          VS2_MUTATION_ROOTS.has(root) ||
          VS3_MUTATION_ROOTS.has(root) ||
          VS4_HEALTH_MUTATION_ROOTS.has(root) ||
          VS5_CONSULTATION_MUTATION_ROOTS.has(root))
      ) {
        queryClient.getMutationCache().remove(mutation);
      }
    }
    setRevealOpen(false);
    setCurrentPin('');
    setRevealedResidentNumber(null);
    setIsRevealPending(false);
    setCreateOpen(false);
    setCloseOpen(false);
    setRehireOpen(false);
    setLicenseForm({ open: false, replacement: null });
    setQualificationForm({ open: false, replacement: null });
    setQualificationCloseTarget(null);
    setHealthFactForm(emptyHealthFactForm());
    setHealthRequirementDrafts({});
    setHealthFactInvalidateTarget(null);
    setHealthRequirementInvalidateTarget(null);
    setHealthFieldErrors({});
    setQuarterlyConsultationForm(emptyQuarterlyConsultationForm());
    setQuarterlyConsultationInvalidateTarget(null);
    setConsultationFieldErrors({});
    setSelectedStaffId(null);
    setSelectedTab('overview');
    setHalfYearTrainingPeriod(currentTrainingPeriodKey('HALF_YEAR'));
    setAnnualTrainingPeriod(currentTrainingPeriodKey('ANNUAL'));
    setBiennialTrainingPeriod(currentTrainingPeriodKey('BIENNIAL'));
    setListScrollTop(0);
    setActionError(null);
  }, [queryClient]);

  useEffect(() => {
    const handleSessionChanged = () => {
      setSessionReady(false);
      purgeStaffSessionData();
    };
    const handleSessionReady = () => setSessionReady(true);
    window.addEventListener(AUTH_SESSION_CHANGED_EVENT, handleSessionChanged);
    window.addEventListener(AUTH_SESSION_READY_EVENT, handleSessionReady);
    return () => {
      window.removeEventListener(AUTH_SESSION_CHANGED_EVENT, handleSessionChanged);
      window.removeEventListener(AUTH_SESSION_READY_EVENT, handleSessionReady);
      purgeStaffSessionData();
    };
  }, [purgeStaffSessionData]);

  const capabilities = capabilitiesQuery.data;
  const canManage = capabilities?.['staff.manage'] === true;
  const canReveal = capabilities?.['staff.sensitive_identity.reveal'] === true;
  const detail = detailQuery.data;
  const employments = detail?.employments ?? [];
  const activeEmployment = detail?.current_employment ?? null;
  const licenseTypes = licenseTypesQuery.data?.items ?? [];
  const serviceTypes = serviceCatalogQuery.data?.items ?? [];
  const licenses = licensesQuery.data?.items ?? [];
  const qualifications = qualificationsQuery.data?.items ?? [];
  const trainingCourses = useMemo(
    () =>
      [...(trainingCoursesQuery.data?.items ?? [])]
        .filter((course) => course.active !== false)
        .sort(
          (left, right) =>
            Number.isFinite(left.sort_order) && Number.isFinite(right.sort_order)
              ? left.sort_order - right.sort_order
              : 0,
        ),
    [trainingCoursesQuery.data?.items],
  );
  const onboardingTrainings = onboardingTrainingsQuery.data?.items ?? [];
  const periodicTrainings = periodicTrainingsQuery.data?.items ?? [];
  const healthFacts = (healthFactsQuery.data?.items ?? []).filter(
    (fact) => fact.invalidated_at_utc == null,
  );
  const healthRequirements = (healthRequirementsQuery.data?.items ?? []).filter(
    (requirement) => requirement.invalidated_at_utc == null,
  );
  const quarterlyConsultations = (
    quarterlyConsultationsQuery.data?.items ?? []
  ).filter((consultation) => consultation.invalidated_at_utc == null);
  const activeLicenses = licenses.filter(
    (license) => license.invalidated_at_utc === null || license.invalidated_at_utc === undefined,
  );
  const continuingEducationCourse = trainingCourses.find(
    (course) => course.code === 'CONTINUING_EDUCATION' && course.cycle_type === 'BIENNIAL',
  );
  const careWorkerIssuedDate = activeLicenses
    .filter((license) => license.license_type_code === 'CARE_WORKER')
    .map((license) => license.issued_date)
    .sort()[0];
  const isWorkingCareWorker = (detail?.current_positions ?? []).some(
    (position) => position.position_code === 'CARE_WORKER',
  );
  const continuingEducation = evaluateContinuingEducation({
    birthDate: detail?.birth_date,
    careWorkerIssuedDate,
    isWorkingCareWorker,
    targetYear: Number(biennialTrainingPeriod),
  });
  const continuingEducationTraining = continuingEducationCourse
    ? periodicTrainings.find(
        (training) =>
          training.invalidated_at_utc == null &&
          training.course_code === continuingEducationCourse.code &&
          training.period_key === biennialTrainingPeriod,
      )
    : undefined;
  const sortedStaffItems = useMemo(() => {
    const items = [...(listQuery.data?.items ?? [])];
    return items.sort((left, right) => {
      if (sort === 'staff_no') {
        return (left.current_employment?.staff_no ?? '').localeCompare(
          right.current_employment?.staff_no ?? '',
        );
      }
      return (left.display_name || left.name).localeCompare(right.display_name || right.name);
    });
  }, [listQuery.data?.items, sort]);

  const positionsByEmployment = useMemo(() => {
    const result = new Map<number, string[]>();
    for (const position of detail?.positions ?? []) {
      const values = result.get(position.employment_id) ?? [];
      values.push(position.position_code);
      result.set(position.employment_id, values);
    }
    return result;
  }, [detail?.positions]);

  const rolesByEmployment = useMemo(() => {
    const result = new Map<number, string[]>();
    for (const role of detail?.operational_roles ?? []) {
      const values = result.get(role.employment_id) ?? [];
      values.push(role.role_code);
      result.set(role.employment_id, values);
    }
    return result;
  }, [detail?.operational_roles]);

  const openHealthFactCreate = () => {
    setHealthFactForm(emptyHealthFactForm());
    setHealthFactForm((current) => ({ ...current, open: true }));
    setHealthFieldErrors({});
    setActionError(null);
  };

  const openHealthFactEdit = (fact: StaffHealthCheckResponse) => {
    setHealthFactForm({
      open: true,
      editing: fact,
      checkDate: fact.check_date,
      employmentId: fact.employment_id === null ? '' : String(fact.employment_id),
      checkTypeCode: fact.check_type_code ?? '',
      resultNote: fact.result_note ?? '',
    });
    setHealthFieldErrors({});
    setActionError(null);
  };

  const closeHealthFactForm = () => {
    if (healthMutationPending) return;
    setHealthFactForm(emptyHealthFactForm());
    setHealthFieldErrors({});
  };

  const submitHealthFact = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail) return;
    setActionError(null);
    setHealthFieldErrors({});
    const checkDate = healthFactForm.checkDate.trim();
    if (!checkDate) {
      setHealthFieldErrors({ check_date: '검진일을 입력해주세요.' });
      setActionError('입력값을 확인해주세요.');
      return;
    }
    const employmentId = healthFactForm.employmentId
      ? Number(healthFactForm.employmentId)
      : null;
    const payloadBase = {
      check_date: checkDate,
      check_type_code: healthFactForm.checkTypeCode.trim() || null,
      employment_id: employmentId,
      result_note: healthFactForm.resultNote.trim() || null,
    };
    const context = {
      staffId: detail.id,
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: healthSelectionEpochRef.current,
    };
    if (healthFactForm.editing) {
      healthFactUpdateMutation.mutate({
        ...context,
        healthCheckId: healthFactForm.editing.id,
        payload: {
          ...payloadBase,
          expected_row_version: healthFactForm.editing.row_version,
        },
      });
      return;
    }
    healthFactCreateMutation.mutate({
      ...context,
      payload: payloadBase,
    });
  };

  const confirmHealthFactInvalidate = () => {
    if (!detail || !healthFactInvalidateTarget) return;
    healthFactInvalidateMutation.mutate({
      staffId: detail.id,
      healthCheckId: healthFactInvalidateTarget.id,
      payload: { expected_row_version: healthFactInvalidateTarget.row_version },
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: healthSelectionEpochRef.current,
    });
  };

  const updateHealthRequirementDraft = (
    requirement: StaffHealthCheckRequirementResponse,
    update: Partial<HealthRequirementDraft>,
  ) => {
    setHealthRequirementDrafts((current) => {
      const existing =
        current[requirement.id] ?? {
          status: requirement.status,
          healthCheckId: requirement.health_check_id === null ? '' : String(requirement.health_check_id),
          exemptReasonText: requirement.exempt_reason_text ?? '',
        };
      const next = { ...existing, ...update };
      if (next.status !== 'COMPLETE') next.healthCheckId = '';
      if (next.status !== 'EXEMPT') next.exemptReasonText = '';
      return { ...current, [requirement.id]: next };
    });
    setHealthFieldErrors({});
    setActionError(null);
  };

  const submitHealthRequirement = (requirement: StaffHealthCheckRequirementResponse) => {
    if (!detail || !canManage) return;
    const draft = healthRequirementDrafts[requirement.id] ?? {
      status: requirement.status,
      healthCheckId: requirement.health_check_id === null ? '' : String(requirement.health_check_id),
      exemptReasonText: requirement.exempt_reason_text ?? '',
    };
    const healthCheckId = draft.healthCheckId ? Number(draft.healthCheckId) : null;
    const exemptReasonText = draft.exemptReasonText.trim();
    if (draft.status === 'COMPLETE' && healthCheckId === null) {
      setHealthFieldErrors({ health_check_id: '완료 상태에는 검진사실을 선택해주세요.' });
      setActionError('입력값을 확인해주세요.');
      return;
    }
    if (draft.status === 'EXEMPT' && !exemptReasonText) {
      setHealthFieldErrors({ exempt_reason_text: '면제사유를 입력해주세요.' });
      setActionError('입력값을 확인해주세요.');
      return;
    }
    setHealthFieldErrors({});
    setActionError(null);
    healthRequirementUpdateMutation.mutate({
      staffId: detail.id,
      requirementId: requirement.id,
      payload: {
        status: draft.status,
        health_check_id: draft.status === 'COMPLETE' ? healthCheckId : null,
        exempt_reason_text: draft.status === 'EXEMPT' ? exemptReasonText : null,
        expected_row_version: requirement.row_version,
      },
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: healthSelectionEpochRef.current,
    });
  };

  const confirmHealthRequirementInvalidate = () => {
    if (!detail || !healthRequirementInvalidateTarget) return;
    healthRequirementInvalidateMutation.mutate({
      staffId: detail.id,
      requirementId: healthRequirementInvalidateTarget.id,
      payload: { expected_row_version: healthRequirementInvalidateTarget.row_version },
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: healthSelectionEpochRef.current,
    });
  };

  const openQuarterlyConsultationCreate = () => {
    setQuarterlyConsultationForm(emptyQuarterlyConsultationForm());
    setQuarterlyConsultationForm((current) => ({ ...current, mode: 'create' }));
    setQuarterlyConsultationInvalidateTarget(null);
    setConsultationFieldErrors({});
    setActionError(null);
  };

  const openQuarterlyConsultationEdit = (
    consultation: StaffQuarterlyConsultationResponse,
  ) => {
    setQuarterlyConsultationForm({
      mode: 'edit',
      editing: consultation,
      calendarYear: String(consultation.calendar_year),
      quarterNo: String(consultation.quarter_no),
      status: consultation.status,
      counselingDate: consultation.counseling_date ?? '',
      content: consultation.content ?? '',
      incompleteReasonText: consultation.incomplete_reason_text ?? '',
      exemptReasonText: consultation.exempt_reason_text ?? '',
    });
    setQuarterlyConsultationInvalidateTarget(null);
    setConsultationFieldErrors({});
    setActionError(null);
  };

  const openQuarterlyConsultationReplace = (
    consultation: StaffQuarterlyConsultationResponse,
  ) => {
    setQuarterlyConsultationForm({
      mode: 'replace',
      editing: consultation,
      calendarYear: String(consultation.calendar_year),
      quarterNo: String(consultation.quarter_no),
      status: consultation.status,
      counselingDate: consultation.counseling_date ?? '',
      content: consultation.content ?? '',
      incompleteReasonText: consultation.incomplete_reason_text ?? '',
      exemptReasonText: consultation.exempt_reason_text ?? '',
    });
    setQuarterlyConsultationInvalidateTarget(consultation);
    setConsultationFieldErrors({});
    setActionError(null);
  };

  const closeQuarterlyConsultationForm = () => {
    if (consultationMutationPending) return;
    setQuarterlyConsultationForm(emptyQuarterlyConsultationForm());
    setQuarterlyConsultationInvalidateTarget(null);
    setConsultationFieldErrors({});
  };

  const updateQuarterlyConsultationForm = (
    update: Partial<QuarterlyConsultationFormState>,
  ) => {
    setQuarterlyConsultationForm((current) => {
      const next = { ...current, ...update };
      if (update.status !== undefined) {
        if (next.status !== 'COMPLETE') {
          next.counselingDate = '';
          next.content = '';
        }
        if (next.status !== 'INCOMPLETE') next.incompleteReasonText = '';
        if (next.status !== 'EXEMPT') next.exemptReasonText = '';
      }
      return next;
    });
    setConsultationFieldErrors({});
    setActionError(null);
  };

  const submitQuarterlyConsultation = (
    event: React.FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    if (!detail || !canManage || !quarterlyConsultationForm.mode) return;

    setConsultationFieldErrors({});
    setActionError(null);
    const calendarYear = Number(quarterlyConsultationForm.calendarYear.trim());
    const quarterNo = Number(quarterlyConsultationForm.quarterNo.trim());
    const fieldErrors: Record<string, string> = {};

    if (!Number.isSafeInteger(calendarYear)) {
      fieldErrors.calendar_year = '연도를 입력해주세요.';
    }
    if (!Number.isSafeInteger(quarterNo) || quarterNo < 1 || quarterNo > 4) {
      fieldErrors.quarter_no = '분기는 1부터 4까지 입력해주세요.';
    }

    const status = quarterlyConsultationForm.status;
    const counselingDate = quarterlyConsultationForm.counselingDate.trim();
    const content = quarterlyConsultationForm.content.trim();
    const incompleteReasonText = quarterlyConsultationForm.incompleteReasonText.trim();
    const exemptReasonText = quarterlyConsultationForm.exemptReasonText.trim();

    if (status === 'COMPLETE') {
      if (!counselingDate) fieldErrors.counseling_date = '상담일을 입력해주세요.';
      if (!content) fieldErrors.content = '처리내용을 입력해주세요.';
    }
    if (status === 'INCOMPLETE' && !incompleteReasonText) {
      fieldErrors.incomplete_reason_text = '미완료 사유를 입력해주세요.';
    }
    if (status === 'EXEMPT' && !exemptReasonText) {
      fieldErrors.exempt_reason_text = '면제 사유를 입력해주세요.';
    }

    if (Object.keys(fieldErrors).length > 0) {
      setConsultationFieldErrors(fieldErrors);
      setActionError('입력값을 확인해주세요.');
      return;
    }

    const conditionalFields = {
      counseling_date: status === 'COMPLETE' ? counselingDate : null,
      content: status === 'COMPLETE' ? content : null,
      incomplete_reason_text: status === 'INCOMPLETE' ? incompleteReasonText : null,
      exempt_reason_text: status === 'EXEMPT' ? exemptReasonText : null,
    };
    const context = {
      staffId: detail.id,
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: consultationSelectionEpochRef.current,
    };

    if (quarterlyConsultationForm.mode === 'create') {
      consultationCreateMutation.mutate({
        ...context,
        payload: {
          calendar_year: calendarYear,
          quarter_no: quarterNo,
          status,
          ...conditionalFields,
        },
      });
      return;
    }

    const editing = quarterlyConsultationForm.editing;
    if (!editing) return;
    if (quarterlyConsultationForm.mode === 'edit') {
      consultationUpdateMutation.mutate({
        ...context,
        consultationId: editing.id,
        payload: {
          status,
          ...conditionalFields,
          expected_row_version: editing.row_version,
        },
      });
      return;
    }

    consultationInvalidateMutation.mutate({
      ...context,
      consultationId: editing.id,
      payload: {
        status,
        ...conditionalFields,
        expected_row_version: editing.row_version,
      },
    });
  };

  const submitCreate = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setActionError(null);
    const data = new FormData(event.currentTarget);
    const payload: StaffCreateRequest = {
      name: formValue(data, 'name'),
      birth_date: formValue(data, 'birth_date'),
      sex_code: formValue(data, 'sex_code') as StaffCreateRequest['sex_code'],
      resident_number: formValue(data, 'resident_number'),
      phone: formValue(data, 'phone') || null,
      address: formValue(data, 'address') || null,
      display_name: formValue(data, 'display_name') || null,
      memo: formValue(data, 'memo') || null,
      initial_employment: {
        start_date: formValue(data, 'start_date'),
      },
    };
    createPayloadRef.current = payload;
    createMutation.mutate({ sessionEpoch: sessionEpochRef.current });
  };

  const submitClose = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail || !activeEmployment) return;
    const data = new FormData(event.currentTarget);
    const payload: StaffEmploymentCloseRequest = {
      end_date: formValue(data, 'end_date'),
      end_reason_code: formValue(data, 'end_reason_code') || null,
      expected_employment_row_version: activeEmployment.row_version,
      open_position_versions: (detail.positions ?? [])
        .filter(
          (period) =>
            period.employment_id === activeEmployment.id && period.end_date === null,
        )
        .map((period) => ({
          period_id: period.id,
          expected_row_version: period.row_version,
        })),
      open_operational_role_versions: (detail.operational_roles ?? [])
        .filter(
          (period) =>
            period.employment_id === activeEmployment.id && period.end_date === null,
        )
        .map((period) => ({
          period_id: period.id,
          expected_row_version: period.row_version,
        })),
    };
    closeMutation.mutate({
      staffId: detail.id,
      employmentId: activeEmployment.id,
      payload,
      sessionEpoch: sessionEpochRef.current,
    });
  };

  const submitRehire = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail) return;
    const data = new FormData(event.currentTarget);
    rehireMutation.mutate({
      staffId: detail.id,
      expectedStaffRowVersion: detail.row_version,
      startDate: formValue(data, 'start_date'),
      sessionEpoch: sessionEpochRef.current,
    });
  };

  const submitLicense = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail) return;
    setActionError(null);
    const data = new FormData(event.currentTarget);
    const payload = {
      license_type_code: formValue(data, 'license_type_code'),
      license_number: formValue(data, 'license_number'),
      issued_date: formValue(data, 'issued_date'),
      expected_row_version: licenseForm.replacement?.row_version ?? detail.row_version,
    };
    if (licenseForm.replacement) {
      licenseReplacementMutation.mutate({
        staffId: detail.id,
        licenseId: licenseForm.replacement.id,
        payload,
        sessionEpoch: sessionEpochRef.current,
      });
      return;
    }
    licenseCreateMutation.mutate({
      staffId: detail.id,
      payload,
      sessionEpoch: sessionEpochRef.current,
    });
  };

  const submitQualification = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail) return;
    setActionError(null);
    const data = new FormData(event.currentTarget);
    const sourceLicense = formValue(data, 'source_license_id');
    const employmentId = Number(formValue(data, 'employment_id'));
    const employment = employments.find((item) => item.id === employmentId);
    const payload = {
      employment_id: employmentId,
      service_type_code: formValue(data, 'service_type_code'),
      start_date: formValue(data, 'start_date'),
      end_date: formValue(data, 'end_date') || null,
      source_license_id: sourceLicense ? Number(sourceLicense) : null,
      expected_row_version:
        qualificationForm.replacement?.row_version ?? employment?.row_version ?? detail.row_version,
    };
    if (qualificationForm.replacement) {
      qualificationReplacementMutation.mutate({
        staffId: detail.id,
        qualificationId: qualificationForm.replacement.id,
        payload,
        sessionEpoch: sessionEpochRef.current,
      });
      return;
    }
    qualificationCreateMutation.mutate({
      staffId: detail.id,
      payload,
      sessionEpoch: sessionEpochRef.current,
    });
  };

  const submitQualificationClose = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail || !qualificationCloseTarget) return;
    setActionError(null);
    const data = new FormData(event.currentTarget);
    qualificationCloseMutation.mutate({
      staffId: detail.id,
      qualificationId: qualificationCloseTarget.id,
      payload: {
        end_date: formValue(data, 'qualification_end_date'),
        expected_row_version: qualificationCloseTarget.row_version,
      },
      sessionEpoch: sessionEpochRef.current,
    });
  };

  const invalidateLicense = (license: StaffLicenseResponse) => {
    if (!detail) return;
    setActionError(null);
    licenseInvalidateMutation.mutate({
      staffId: detail.id,
      licenseId: license.id,
      payload: { expected_row_version: license.row_version },
      sessionEpoch: sessionEpochRef.current,
    });
  };

  const invalidateQualification = (qualification: StaffServiceQualificationResponse) => {
    if (!detail) return;
    setActionError(null);
    qualificationInvalidateMutation.mutate({
      staffId: detail.id,
      qualificationId: qualification.id,
      payload: { expected_row_version: qualification.row_version },
      sessionEpoch: sessionEpochRef.current,
    });
  };

  const toggleOnboardingTraining = (
    training: StaffOnboardingTrainingResponse,
    completed: boolean,
  ) => {
    if (!detail || !canManage) return;
    setActionError(null);
    onboardingUpdateMutation.mutate({
      staffId: detail.id,
      trainingId: training.id,
      payload: {
        completed,
        expected_row_version: training.row_version,
      },
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: trainingSelectionEpochRef.current,
    });
  };

  const togglePeriodicTraining = (
    course: TrainingCourseResponse,
    training: StaffPeriodicTrainingResponse | undefined,
    periodKey: string,
    completed: boolean,
  ) => {
    if (!detail || !canManage) return;
    setActionError(null);
    if (training) {
      periodicUpdateMutation.mutate({
        staffId: detail.id,
        trainingId: training.id,
        payload: {
          completed,
          expected_row_version: training.row_version,
        },
        sessionEpoch: sessionEpochRef.current,
        staffSelectionEpoch: trainingSelectionEpochRef.current,
      });
      return;
    }
    if (!completed) return;
    periodicCreateMutation.mutate({
      staffId: detail.id,
      payload: {
        course_code: course.code,
        period_key: periodKey,
        completed: true,
        expected_row_version: detail.row_version,
      },
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: trainingSelectionEpochRef.current,
    });
  };

  const invalidatePeriodic = (training: StaffPeriodicTrainingResponse) => {
    if (!detail || !canManage) return;
    setActionError(null);
    periodicInvalidateMutation.mutate({
      staffId: detail.id,
      trainingId: training.id,
      payload: { expected_row_version: training.row_version },
      sessionEpoch: sessionEpochRef.current,
      staffSelectionEpoch: trainingSelectionEpochRef.current,
    });
  };

  const submitReveal = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!detail) return;
    revealAbortRef.current?.abort();
    const controller = new AbortController();
    revealAbortRef.current = controller;
    const requestId = ++revealRequestIdRef.current;
    const pin = currentPin;
    setCurrentPin('');
    setIsRevealPending(true);
    setActionError(null);
    try {
      const result = await revealSensitiveIdentity(detail.id, pin, controller.signal);
      if (requestId !== revealRequestIdRef.current || controller.signal.aborted) return;
      setRevealedResidentNumber(result.resident_number);
    } catch (error: unknown) {
      if (
        requestId !== revealRequestIdRef.current ||
        controller.signal.aborted ||
        (error instanceof Error && error.name === 'AbortError')
      ) {
        return;
      }
      handleMutationError(error);
    } finally {
      if (requestId === revealRequestIdRef.current) {
        revealAbortRef.current = null;
        setIsRevealPending(false);
      }
    }
  };

  const closeReveal = () => {
    revealRequestIdRef.current += 1;
    revealAbortRef.current?.abort();
    revealAbortRef.current = null;
    setRevealOpen(false);
    setCurrentPin('');
    setRevealedResidentNumber(null);
    setIsRevealPending(false);
    setActionError(null);
  };

  const selectStaff = (staffId: number) => {
    changeStaffSelection(staffId);
    if (
      typeof window === 'undefined' ||
      staffIdFromLocation() === staffId ||
      new URLSearchParams(window.location.search).has('context')
    ) {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    params.set('staff_id', String(staffId));
    const query = params.toString();
    window.history.pushState(
      { ...(window.history.state as Record<string, unknown> | null), staffId },
      '',
      `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
    );
  };

  const renderQuarterlyConsultationFields = (includeKeyFields: boolean) => (
    <>
      {includeKeyFields ? (
        <>
          <label>
            연도
            <input
              type="number"
              value={quarterlyConsultationForm.calendarYear}
              onChange={(event) =>
                updateQuarterlyConsultationForm({ calendarYear: event.target.value })
              }
            />
            {consultationFieldErrors.calendar_year && (
              <span className="staff-field-error">
                {consultationFieldErrors.calendar_year}
              </span>
            )}
          </label>
          <label>
            분기
            <select
              value={quarterlyConsultationForm.quarterNo}
              onChange={(event) =>
                updateQuarterlyConsultationForm({ quarterNo: event.target.value })
              }
            >
              <option value="1">1분기</option>
              <option value="2">2분기</option>
              <option value="3">3분기</option>
              <option value="4">4분기</option>
            </select>
            {consultationFieldErrors.quarter_no && (
              <span className="staff-field-error">
                {consultationFieldErrors.quarter_no}
              </span>
            )}
          </label>
        </>
      ) : (
        <div className="staff-quarterly-consultation-key">
          <span>연도</span>
          <strong>{quarterlyConsultationForm.calendarYear}</strong>
          <span>분기</span>
          <strong>{quarterlyConsultationForm.quarterNo}분기</strong>
        </div>
      )}
      <label>
        상태
        <select
          value={quarterlyConsultationForm.status}
          onChange={(event) =>
            updateQuarterlyConsultationForm({
              status: event.target.value as QuarterlyConsultationStatus,
            })
          }
          disabled={consultationMutationPending}
        >
          <option value="COMPLETE">COMPLETE</option>
          <option value="INCOMPLETE">INCOMPLETE</option>
          <option value="EXEMPT">EXEMPT</option>
        </select>
      </label>
      {quarterlyConsultationForm.status === 'COMPLETE' && (
        <>
          <label>
            상담일
            <input
              type="date"
              value={quarterlyConsultationForm.counselingDate}
              onChange={(event) =>
                updateQuarterlyConsultationForm({ counselingDate: event.target.value })
              }
              disabled={consultationMutationPending}
            />
            {consultationFieldErrors.counseling_date && (
              <span className="staff-field-error">
                {consultationFieldErrors.counseling_date}
              </span>
            )}
          </label>
          <label className="staff-form-wide">
            처리내용
            <textarea
              rows={3}
              value={quarterlyConsultationForm.content}
              onChange={(event) =>
                updateQuarterlyConsultationForm({ content: event.target.value })
              }
              disabled={consultationMutationPending}
            />
            {consultationFieldErrors.content && (
              <span className="staff-field-error">{consultationFieldErrors.content}</span>
            )}
          </label>
        </>
      )}
      {quarterlyConsultationForm.status === 'INCOMPLETE' && (
        <label className="staff-form-wide">
          미완료 사유
          <textarea
            rows={3}
            value={quarterlyConsultationForm.incompleteReasonText}
            onChange={(event) =>
              updateQuarterlyConsultationForm({
                incompleteReasonText: event.target.value,
              })
            }
            disabled={consultationMutationPending}
          />
          {consultationFieldErrors.incomplete_reason_text && (
            <span className="staff-field-error">
              {consultationFieldErrors.incomplete_reason_text}
            </span>
          )}
        </label>
      )}
      {quarterlyConsultationForm.status === 'EXEMPT' && (
        <label className="staff-form-wide">
          면제 사유
          <textarea
            rows={3}
            value={quarterlyConsultationForm.exemptReasonText}
            onChange={(event) =>
              updateQuarterlyConsultationForm({ exemptReasonText: event.target.value })
            }
            disabled={consultationMutationPending}
          />
          {consultationFieldErrors.exempt_reason_text && (
            <span className="staff-field-error">
              {consultationFieldErrors.exempt_reason_text}
            </span>
          )}
        </label>
      )}
    </>
  );

  return (
    <div className="staff-page" data-testid="page-staff">
      <header className="staff-page-header">
        <div>
          <h1>직원 관리</h1>
        </div>
        {canManage && (
          <button
            type="button"
            className="staff-button staff-button-primary"
            onClick={() => {
              setActionError(null);
              setCreateOpen(true);
            }}
          >
            신규 직원 등록
          </button>
        )}
      </header>

      {actionError && (
        <div className="staff-alert" role="alert">
          <span>{actionError}</span>
          <button type="button" onClick={() => setActionError(null)}>
            닫기
          </button>
        </div>
      )}
      {!sessionReady && (
        <p className="staff-state" role="status">
          세션을 전환하는 중입니다…
        </p>
      )}

      <section className="staff-workspace" aria-label="직원 목록과 상세">
        <aside className="staff-list-panel">
          <form
            className="staff-search"
            onSubmit={(event) => {
              event.preventDefault();
              setSearch(searchDraft);
              setPage(1);
              setListScrollTop(0);
            }}
          >
            <label htmlFor="staff-search-input">직원 검색</label>
            <div>
              <input
                id="staff-search-input"
                value={searchDraft}
                placeholder="직원 검색"
                onChange={(event) => setSearchDraft(event.target.value)}
              />
              <button type="submit">검색</button>
            </div>
          </form>

          <div className="staff-list-controls" aria-label="직원 목록 문맥">
            <label>
              정렬
              <select
                aria-label="정렬"
                value={sort}
                onChange={(event) => {
                  setSort(event.target.value);
                  setListScrollTop(0);
                }}
              >
                <option value="name">이름순</option>
                <option value="staff_no">직원번호순</option>
              </select>
            </label>
            <div className="staff-pagination">
              <button
                type="button"
                aria-label="이전 페이지"
                disabled={page <= 1}
                onClick={() => {
                  setPage((current) => Math.max(1, current - 1));
                  setListScrollTop(0);
                }}
              >
                이전 페이지
              </button>
              <span data-testid="staff-page-indicator">{page}</span>
              <button
                type="button"
                aria-label="다음 페이지"
                disabled={(listQuery.data?.items.length ?? 0) === 0}
                onClick={() => {
                  setPage((current) => current + 1);
                  setListScrollTop(0);
                }}
              >
                다음 페이지
              </button>
            </div>
          </div>

          {listQuery.isLoading && <p className="staff-state">직원 목록을 불러오는 중…</p>}
          {listQuery.isError && (
            <p className="staff-state staff-state-error">직원 목록을 불러오지 못했습니다.</p>
          )}
          {!listQuery.isLoading && (listQuery.data?.items.length ?? 0) === 0 && (
            <p className="staff-state">검색 조건에 맞는 직원이 없습니다.</p>
          )}
          <div
            className="staff-list"
            data-testid="staff-list-scroll"
            role="list"
            ref={listScrollRef}
            onScroll={(event) => setListScrollTop(event.currentTarget.scrollTop)}
          >
            {sortedStaffItems.map((staff) => (
              <button
                type="button"
                role="listitem"
                key={staff.id}
                className={staff.id === selectedStaffId ? 'selected' : ''}
                onClick={() => selectStaff(staff.id)}
              >
                <span className="staff-list-name">{staff.display_name || staff.name}</span>
                <span>
                  {staff.current_employment?.staff_no ?? '재직번호 없음'}
                  {' · '}
                  {staff.current_employment?.status === 'ACTIVE' ? '재직' : '퇴직'}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="staff-detail-panel" data-testid="staff-detail-workspace">
          {detailQuery.isLoading && (
            <p className="staff-state">직원 상세를 불러오는 중…</p>
          )}
          {detailQuery.isError && (
            <p className="staff-state staff-state-error">직원 상세를 불러오지 못했습니다.</p>
          )}
          {!selectedStaffId && (
            <p className="staff-state">목록에서 직원을 선택하거나 새 직원을 등록하세요.</p>
          )}
          {selectedStaffId !== null && (
            <>
              {detail && (
                <>
                  <div className="staff-detail-heading">
                <div>
                  <p className="staff-eyebrow">직원 #{detail.id}</p>
                  <h2>{detail.display_name || detail.name}</h2>
                  <p>
                    {detail.name} · {detail.birth_date} ·{' '}
                    {detail.sex_code === 'MALE' ? '남성' : '여성'}
                  </p>
                </div>
                <div className="staff-detail-actions">
                  {canManage &&
                    (activeEmployment ? (
                      <button type="button" onClick={() => setCloseOpen(true)}>
                        재직 종료
                      </button>
                    ) : (
                      <button type="button" onClick={() => setRehireOpen(true)}>
                        재입사
                      </button>
                    ))}
                </div>
                  </div>

              {selectedTab === 'overview' && (
                <>
                  <section className="staff-info-grid" aria-label="직원 기본정보">
                <div>
                  <span>전화번호</span>
                  <strong>{detail.phone ?? '미등록'}</strong>
                </div>
                <div>
                  <span>주소</span>
                  <strong>{detail.address ?? '미등록'}</strong>
                </div>
                <div>
                  <span>메모</span>
                  <strong>{detail.memo ?? '없음'}</strong>
                </div>
                <div className="staff-sensitive-summary">
                  <span>주민등록번호</span>
                  <strong>{detail.resident_number_masked ?? '미등록'}</strong>
                  {canReveal && detail.resident_number_masked && (
                    <button
                      type="button"
                      onClick={() => {
                        setCurrentPin('');
                        setRevealedResidentNumber(null);
                        setActionError(null);
                        setRevealOpen(true);
                      }}
                    >
                      주민번호 보기
                    </button>
                  )}
                </div>
                  </section>

                  <section className="staff-history-section">
                <h3>재직 이력</h3>
                <div className="staff-history-list" data-testid="staff-employment-list">
                  {employments.map((employment) => (
                    <article key={employment.id}>
                      <strong>{employment.staff_no}</strong>
                      <span>
                        {employment.start_date} ~ {employment.end_date ?? '재직 중'}
                      </span>
                      <span>
                        직종{' '}
                        {positionsByEmployment.get(employment.id)?.join(', ') ||
                          '미등록'}
                        {' · 역할 '}
                        {rolesByEmployment.get(employment.id)?.join(', ') || '미등록'}
                      </span>
                    </article>
                  ))}
                </div>
                  </section>

                  <div className="staff-history-columns">
                <section className="staff-history-section">
                  <h3>직종 이력</h3>
                  <div className="staff-history-list">
                    {(detail.positions ?? []).map((period) => (
                      <article key={period.id}>
                        <strong>{period.position_code}</strong>
                        <span>
                          {period.start_date} ~ {period.end_date ?? '현재'}
                        </span>
                      </article>
                    ))}
                    {(detail.positions?.length ?? 0) === 0 && <p>등록된 직종이 없습니다.</p>}
                  </div>
                </section>
                <section className="staff-history-section">
                  <h3>업무역할 이력</h3>
                  <div className="staff-history-list">
                    {(detail.operational_roles ?? []).map((period) => (
                      <article key={period.id}>
                        <strong>{period.role_code}</strong>
                        <span>
                          {period.start_date} ~ {period.end_date ?? '현재'}
                        </span>
                      </article>
                    ))}
                    {(detail.operational_roles?.length ?? 0) === 0 && (
                      <p>등록된 업무역할이 없습니다.</p>
                    )}
                  </div>
                </section>
                  </div>
                </>
              )}

                </>
              )}

              <div className="staff-detail-tabs" role="tablist" aria-label="직원 상세 탭">
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedTab === 'overview'}
                  onClick={() => setSelectedTab('overview')}
                >
                  기본정보
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedTab === 'licenses'}
                  onClick={() => setSelectedTab('licenses')}
                >
                  자격증
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedTab === 'qualifications'}
                  onClick={() => setSelectedTab('qualifications')}
                >
                  서비스 제공자격
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedTab === 'training'}
                  onClick={() => setSelectedTab('training')}
                >
                  교육
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedTab === 'health'}
                  onClick={() => {
                    setHealthFieldErrors({});
                    setActionError(null);
                    setSelectedTab('health');
                  }}
                >
                  검진
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedTab === 'consultation'}
                  onClick={() => {
                    setConsultationFieldErrors({});
                    setActionError(null);
                    setSelectedTab('consultation');
                    if (selectedStaffId !== null) {
                      void queryClient.invalidateQueries({
                        queryKey: ['staff-quarterly-consultations', selectedStaffId],
                      });
                    }
                  }}
                >
                  분기상담
                </button>
              </div>

              {selectedTab === 'licenses' && (
                <section className="staff-qualification-panel" aria-label="자격증">
                  <div className="staff-section-heading">
                    <div>
                      <h3>자격증</h3>
                      <p>직원이 보유한 일반 자격증 사실을 관리합니다.</p>
                    </div>
                    {canManage && !licenseForm.open && (
                      <button
                        type="button"
                        onClick={() => {
                          setActionError(null);
                          setLicenseForm({ open: true, replacement: null });
                        }}
                      >
                        자격증 추가
                      </button>
                    )}
                  </div>

                  {licenseForm.open && (
                    <form
                      className="staff-form staff-qualification-form"
                      data-testid="staff-license-form"
                      onSubmit={submitLicense}
                    >
                      <h4 className="staff-form-title">
                        {licenseForm.replacement ? '자격증 대체' : '자격증 추가'}
                      </h4>
                      <label>
                        자격종류
                        <select
                          name="license_type_code"
                          defaultValue={licenseForm.replacement?.license_type_code ?? ''}
                          required
                        >
                          <option value="">선택</option>
                          {licenseTypes.map((licenseType) => (
                            <option key={licenseType.code} value={licenseType.code}>
                              {licenseType.display_name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        자격번호
                        <input
                          name="license_number"
                          defaultValue={licenseForm.replacement?.license_number ?? ''}
                          required
                        />
                      </label>
                      <label>
                        발급일
                        <input
                          name="issued_date"
                          type="date"
                          defaultValue={licenseForm.replacement?.issued_date ?? ''}
                          required
                        />
                      </label>
                      {licenseTypesQuery.isLoading && (
                        <p className="staff-state">자격종류를 불러오는 중…</p>
                      )}
                      {licenseTypesQuery.isError && (
                        <p className="staff-state staff-state-error">
                          자격종류를 불러오지 못했습니다.
                        </p>
                      )}
                      <div className="staff-form-actions staff-form-wide">
                        <button
                          type="button"
                          onClick={() => setLicenseForm({ open: false, replacement: null })}
                        >
                          취소
                        </button>
                        <button
                          type="submit"
                          className="staff-button-primary"
                          disabled={
                            licenseCreateMutation.isPending ||
                            licenseReplacementMutation.isPending
                          }
                        >
                          {licenseCreateMutation.isPending || licenseReplacementMutation.isPending
                            ? '저장 중…'
                            : licenseForm.replacement
                              ? '대체 저장'
                              : '자격증 등록'}
                        </button>
                      </div>
                    </form>
                  )}

                  {licensesQuery.isLoading && (
                    <p className="staff-state">자격증 목록을 불러오는 중…</p>
                  )}
                  {licensesQuery.isError && (
                    <p className="staff-state staff-state-error">
                      자격증 목록을 불러오지 못했습니다.
                    </p>
                  )}
                  {!licensesQuery.isLoading && !licensesQuery.isError && licenses.length === 0 && (
                    <p className="staff-state">등록된 자격증이 없습니다.</p>
                  )}
                  <div className="staff-qualification-list">
                    {licenses.map((license) => {
                      const active =
                        license.invalidated_at_utc === null ||
                        license.invalidated_at_utc === undefined;
                      return (
                        <article
                          className="staff-qualification-row"
                          data-testid="staff-license-row"
                          key={license.id}
                        >
                          <div>
                            <strong>
                              {license.license_type_display_name || license.license_type_code}
                            </strong>
                            <span>{license.license_number}</span>
                            <span>발급일 {license.issued_date}</span>
                          </div>
                          <div className="staff-row-actions">
                            {!active && <span className="staff-state-badge">무효화됨</span>}
                            {canManage && active && (
                              <>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setLicenseForm({ open: true, replacement: license })
                                  }
                                >
                                  자격증 대체
                                </button>
                                <button type="button" onClick={() => invalidateLicense(license)}>
                                  자격증 무효화
                                </button>
                              </>
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              )}

              {selectedTab === 'qualifications' && (
                <section className="staff-qualification-panel" aria-label="서비스 제공자격">
                  <div className="staff-section-heading">
                    <div>
                      <h3>서비스 제공자격</h3>
                      <p>재직 범위 안의 서비스 제공자격 기간을 관리합니다.</p>
                    </div>
                    {canManage && !qualificationForm.open && (
                      <button
                        type="button"
                        onClick={() => {
                          setActionError(null);
                          setQualificationForm({ open: true, replacement: null });
                        }}
                      >
                        서비스 제공자격 추가
                      </button>
                    )}
                  </div>

                  {qualificationForm.open && (
                    <form
                      className="staff-form staff-qualification-form"
                      data-testid="staff-qualification-form"
                      onSubmit={submitQualification}
                    >
                      <h4 className="staff-form-title">
                        {qualificationForm.replacement
                          ? '서비스 제공자격 대체'
                          : '서비스 제공자격 추가'}
                      </h4>
                      <label>
                        재직
                        <select
                          name="employment_id"
                          defaultValue={
                            String(
                              qualificationForm.replacement?.employment_id ??
                                activeEmployment?.id ??
                                '',
                            )
                          }
                          required
                        >
                          <option value="">선택</option>
                          {employments.map((employment) => (
                            <option key={employment.id} value={employment.id}>
                              {employment.staff_no} · {employment.start_date} ~{' '}
                              {employment.end_date ?? '재직 중'}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        서비스종류
                        <select
                          name="service_type_code"
                          defaultValue={
                            qualificationForm.replacement?.service_type_code ?? ''
                          }
                          required
                        >
                          <option value="">선택</option>
                          {serviceTypes.map((serviceType) => (
                            <option key={serviceType.code} value={serviceType.code}>
                              {serviceType.display_name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        시작일
                        <input
                          name="start_date"
                          type="date"
                          defaultValue={qualificationForm.replacement?.start_date ?? ''}
                          required
                        />
                      </label>
                      <label>
                        종료일
                        <input
                          name="end_date"
                          type="date"
                          defaultValue={qualificationForm.replacement?.end_date ?? ''}
                        />
                      </label>
                      <label className="staff-form-wide">
                        근거 자격증 (선택)
                        <select
                          name="source_license_id"
                          defaultValue={
                            qualificationForm.replacement?.source_license_id == null
                              ? ''
                              : String(qualificationForm.replacement.source_license_id)
                          }
                        >
                          <option value="">자격증 없이 제공자격 등록</option>
                          {activeLicenses.map((license) => (
                            <option key={license.id} value={license.id}>
                              {license.license_type_display_name || license.license_type_code} ·{' '}
                              {license.license_number}
                            </option>
                          ))}
                        </select>
                      </label>
                      {serviceCatalogQuery.isLoading && (
                        <p className="staff-state">서비스 종류를 불러오는 중…</p>
                      )}
                      {serviceCatalogQuery.isError && (
                        <p className="staff-state staff-state-error">
                          서비스 종류를 불러오지 못했습니다.
                        </p>
                      )}
                      <div className="staff-form-actions staff-form-wide">
                        <button
                          type="button"
                          onClick={() =>
                            setQualificationForm({ open: false, replacement: null })
                          }
                        >
                          취소
                        </button>
                        <button
                          type="submit"
                          className="staff-button-primary"
                          disabled={
                            qualificationCreateMutation.isPending ||
                            qualificationReplacementMutation.isPending
                          }
                        >
                          {qualificationCreateMutation.isPending ||
                          qualificationReplacementMutation.isPending
                            ? '저장 중…'
                            : qualificationForm.replacement
                              ? '대체 저장'
                              : '서비스 제공자격 등록'}
                        </button>
                      </div>
                    </form>
                  )}

                  {qualificationCloseTarget && (
                    <form
                      className="staff-inline-form"
                      data-testid="staff-qualification-close-form"
                      onSubmit={submitQualificationClose}
                    >
                      <label>
                        종료일
                        <input name="qualification_end_date" type="date" required />
                      </label>
                      <button
                        type="button"
                        onClick={() => setQualificationCloseTarget(null)}
                      >
                        취소
                      </button>
                      <button
                        type="submit"
                        className="staff-button-primary"
                        disabled={qualificationCloseMutation.isPending}
                      >
                        {qualificationCloseMutation.isPending ? '저장 중…' : '종료 저장'}
                      </button>
                    </form>
                  )}

                  {qualificationsQuery.isLoading && (
                    <p className="staff-state">서비스 제공자격을 불러오는 중…</p>
                  )}
                  {qualificationsQuery.isError && (
                    <p className="staff-state staff-state-error">
                      서비스 제공자격을 불러오지 못했습니다.
                    </p>
                  )}
                  {!qualificationsQuery.isLoading &&
                    !qualificationsQuery.isError &&
                    qualifications.length === 0 && (
                      <p className="staff-state">등록된 서비스 제공자격이 없습니다.</p>
                    )}
                  <div className="staff-qualification-list">
                    {qualifications.map((qualification) => {
                      const active =
                        qualification.invalidated_at_utc === null ||
                        qualification.invalidated_at_utc === undefined;
                      return (
                        <article
                          className="staff-qualification-row"
                          data-testid="staff-qualification-row"
                          key={qualification.id}
                        >
                          <div>
                            <strong>
                              {qualification.service_type_display_name ||
                                qualification.service_type_code}
                            </strong>
                            <span>
                              {qualification.start_date} ~ {qualification.end_date ?? '현재'}
                            </span>
                            <span>
                              {qualification.source_license_id == null
                                ? '근거 자격증 없음'
                                : `근거 자격증 #${qualification.source_license_id}`}
                            </span>
                          </div>
                          <div className="staff-row-actions">
                            {!active && <span className="staff-state-badge">무효화됨</span>}
                            {canManage && active && (
                              <>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setQualificationForm({
                                      open: true,
                                      replacement: qualification,
                                    })
                                  }
                                >
                                  서비스 제공자격 대체
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setQualificationCloseTarget(qualification)}
                                >
                                  서비스 제공자격 종료
                                </button>
                                <button
                                  type="button"
                                  onClick={() => invalidateQualification(qualification)}
                                >
                                  서비스 제공자격 무효화
                                </button>
                              </>
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </section>
              )}

              {selectedTab === 'training' && (
                <section className="staff-training-panel" aria-label="교육">
                  <div className="staff-section-heading">
                    <div>
                      <h3>교육</h3>
                    </div>
                  </div>

                  {trainingCoursesQuery.isLoading && (
                    <p className="staff-state">교육과목을 불러오는 중…</p>
                  )}
                  {trainingCoursesQuery.isError && (
                    <p className="staff-state staff-state-error">
                      교육과목을 불러오지 못했습니다.
                    </p>
                  )}
                  {!trainingCoursesQuery.isLoading &&
                    !trainingCoursesQuery.isError &&
                    trainingCourses.length === 0 && (
                      <p className="staff-state">등록된 교육과목이 없습니다.</p>
                    )}
                  {trainingCourses.length > 0 && (
                    <div className="staff-training-course-list" aria-label="교육과목 목록" hidden>
                      {trainingCourses.map((course) => (
                        <article
                          className="staff-training-course-row"
                          data-testid="training-course-row"
                          data-course-code={course.code}
                          data-cycle-type={course.cycle_type}
                          data-cycle-label={cycleLabel(course.cycle_type)}
                          aria-label={`${course.display_name} ${cycleLabel(course.cycle_type)}`}
                          key={course.code}
                        >
                          {course.display_name}
                        </article>
                      ))}
                    </div>
                  )}

                  <section
                    className="staff-training-section"
                    aria-label="신규직원교육"
                    data-testid="staff-onboarding-training-panel"
                  >
                    <div className="staff-section-heading">
                      <div>
                        <h3>신규직원교육</h3>
                      </div>
                    </div>
                    {onboardingTrainingsQuery.isLoading && (
                      <p className="staff-state">신규직원교육을 불러오는 중…</p>
                    )}
                    {onboardingTrainingsQuery.isError && (
                      <p className="staff-state staff-state-error">
                        신규직원교육을 불러오지 못했습니다.
                      </p>
                    )}
                    {!onboardingTrainingsQuery.isLoading &&
                      !onboardingTrainingsQuery.isError &&
                      onboardingTrainings.length === 0 && (
                        <p className="staff-state">등록된 신규직원교육이 없습니다.</p>
                      )}
                    <div className="staff-training-check-list">
                      {onboardingTrainings.map((training) => {
                        const employment = employments.find(
                          (item) => item.id === training.employment_id,
                        );
                        const course = trainingCourses.find(
                          (item) => item.code === training.course_code,
                        );
                        return (
                          <label className="staff-training-check-row" key={training.id}>
                            <input
                              type="checkbox"
                              checked={training.completed}
                              disabled={!canManage || trainingMutationPending}
                              onChange={(event) =>
                                toggleOnboardingTraining(training, event.target.checked)
                              }
                            />
                            <span>
                              {course?.display_name ?? training.course_code}
                              {employment?.staff_no ? ` · ${employment.staff_no}` : ''}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </section>

                  <section
                    className="staff-training-section"
                    aria-label="정기교육"
                    data-testid="staff-periodic-training-panel"
                  >
                    <div className="staff-section-heading">
                      <div>
                        <h3>정기교육</h3>
                      </div>
                    </div>
                    <div className="staff-training-period-controls">
                      <label>
                        반기 대상기간
                        <select
                          aria-label="반기 대상기간"
                          value={halfYearTrainingPeriod}
                          disabled={trainingMutationPending}
                          onChange={(event) => setHalfYearTrainingPeriod(event.target.value)}
                        >
                          {trainingPeriodOptions('HALF_YEAR').map((periodKey) => (
                            <option key={periodKey} value={periodKey}>
                              {periodKey}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        연간 대상기간
                        <select
                          aria-label="연간 대상기간"
                          value={annualTrainingPeriod}
                          disabled={trainingMutationPending}
                          onChange={(event) => setAnnualTrainingPeriod(event.target.value)}
                        >
                          {trainingPeriodOptions('ANNUAL').map((periodKey) => (
                            <option key={periodKey} value={periodKey}>
                              {periodKey}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    {periodicTrainingsQuery.isLoading && (
                      <p className="staff-state">정기교육을 불러오는 중…</p>
                    )}
                    {periodicTrainingsQuery.isError && (
                      <p className="staff-state staff-state-error">
                        정기교육을 불러오지 못했습니다.
                      </p>
                    )}
                    <div className="staff-training-check-list">
                      {trainingCourses
                        .filter(
                          (course) =>
                            course.cycle_type === 'HALF_YEAR' || course.cycle_type === 'ANNUAL',
                        )
                        .map((course) => {
                          const periodKey =
                            course.cycle_type === 'HALF_YEAR'
                              ? halfYearTrainingPeriod
                              : annualTrainingPeriod;
                          const training = periodicTrainings.find(
                            (item) =>
                              item.invalidated_at_utc == null &&
                              item.course_code === course.code &&
                              item.period_key === periodKey,
                          );
                          return (
                            <article
                              className="staff-training-check-row staff-training-period-row"
                              key={`${course.code}-${periodKey}`}
                            >
                              <label>
                                <input
                                  type="checkbox"
                                  checked={training?.completed === true}
                                  disabled={!canManage || trainingMutationPending}
                                  onChange={(event) =>
                                    togglePeriodicTraining(
                                      course,
                                      training,
                                      periodKey,
                                      event.target.checked,
                                    )
                                  }
                                />
                                <span>
                                  {course.display_name} · {periodKey}
                                </span>
                              </label>
                              {canManage && training && (
                                <button
                                  type="button"
                                  disabled={trainingMutationPending}
                                  onClick={() => invalidatePeriodic(training)}
                                >
                                  무효화
                                </button>
                              )}
                            </article>
                          );
                        })}
                    </div>
                  </section>

                  {continuingEducationCourse && (
                    <section
                      className="staff-training-section staff-continuing-education"
                      aria-label="보수교육"
                      data-testid="staff-continuing-education-panel"
                    >
                      <div className="staff-section-heading staff-continuing-heading">
                        <h3>보수교육</h3>
                        <label>
                          대상연도
                          <select
                            aria-label="보수교육 대상연도"
                            value={biennialTrainingPeriod}
                            disabled={trainingMutationPending}
                            onChange={(event) => setBiennialTrainingPeriod(event.target.value)}
                          >
                            {trainingPeriodOptions('BIENNIAL').map((periodKey) => (
                              <option key={periodKey} value={periodKey}>
                                {periodKey}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                      <div
                        className={`staff-continuing-status is-${continuingEducation.status.toLowerCase().replace('_', '-')}`}
                        data-testid="staff-continuing-education-status"
                      >
                        {continuingEducation.status === 'DUE' ? (
                          <label className="staff-training-check-row">
                            <input
                              type="checkbox"
                              data-testid="staff-continuing-education-checkbox"
                              checked={continuingEducationTraining?.completed === true}
                              disabled={!canManage || trainingMutationPending}
                              onChange={(event) =>
                                togglePeriodicTraining(
                                  continuingEducationCourse,
                                  continuingEducationTraining,
                                  biennialTrainingPeriod,
                                  event.target.checked,
                                )
                              }
                            />
                            <span>{biennialTrainingPeriod}년 대상</span>
                          </label>
                        ) : continuingEducation.status === 'EXEMPT' ? (
                          <span>면제 · 최초 자격 취득연도 기준</span>
                        ) : continuingEducation.status === 'NOT_DUE' ? (
                          <span>대상 아님 · 출생연도 홀짝 불일치</span>
                        ) : continuingEducation.status === 'NOT_APPLICABLE' ? (
                          <span>대상 아님 · 현재 요양보호사 직종 아님</span>
                        ) : continuingEducation.status === 'NOT_QUALIFIED_YET' ? (
                          <span>대상 아님 · 해당 연도 자격 취득 전</span>
                        ) : (
                          <span>생년월일과 최초 자격 취득일 확인 필요</span>
                        )}
                      </div>
                    </section>
                  )}
                </section>
              )}

              {selectedTab === 'health' && (
                <section className="staff-health-panel" aria-label="검진">
                  <div className="staff-section-heading">
                    <div>
                      <h3>검진</h3>
                      <p>직원의 검진사실과 이미 부여된 대상별 상태를 관리합니다.</p>
                    </div>
                  </div>

                  <section
                    className="staff-health-ledger"
                    aria-label="검진사실"
                    data-testid="staff-health-check-facts-panel"
                  >
                    <div className="staff-health-ledger-heading">
                      <div>
                        <h4>검진사실</h4>
                        <p>같은 날짜의 여러 검진사실을 등록할 수 있습니다.</p>
                      </div>
                      {canManage && !healthFactForm.open && (
                        <button
                          type="button"
                          data-testid="health-check-fact-add"
                          onClick={openHealthFactCreate}
                        >
                          검진사실 추가
                        </button>
                      )}
                    </div>

                    {healthFactForm.open && canManage && (
                      <form
                        className="staff-form staff-health-fact-form"
                        data-testid="health-check-fact-form"
                        onSubmit={submitHealthFact}
                      >
                        <h4 className="staff-form-title">
                          {healthFactForm.editing ? '검진사실 수정' : '검진사실 추가'}
                        </h4>
                        <label>
                          검진일
                          <input
                            type="date"
                            value={healthFactForm.checkDate}
                            required
                            onChange={(event) =>
                              setHealthFactForm((current) => ({
                                ...current,
                                checkDate: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <label>
                          재직 (선택)
                          <select
                            value={healthFactForm.employmentId}
                            onChange={(event) =>
                              setHealthFactForm((current) => ({
                                ...current,
                                employmentId: event.target.value,
                              }))
                            }
                          >
                            <option value="">선택하지 않음</option>
                            {employments.map((employment) => (
                              <option key={employment.id} value={employment.id}>
                                {employment.staff_no ?? `재직 #${employment.id}`} ·{' '}
                                {employment.start_date} ~ {employment.end_date ?? '재직 중'}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          검진 유형 (선택)
                          <select
                            value={healthFactForm.checkTypeCode}
                            onChange={(event) =>
                              setHealthFactForm((current) => ({
                                ...current,
                                checkTypeCode: event.target.value,
                              }))
                            }
                          >
                            <option value="">선택하지 않음</option>
                            {healthFactForm.checkTypeCode &&
                              !['GENERAL', 'SPECIAL', 'OTHER'].includes(
                                healthFactForm.checkTypeCode,
                              ) && (
                                <option value={healthFactForm.checkTypeCode}>
                                  {healthFactForm.checkTypeCode}
                                </option>
                              )}
                            <option value="GENERAL">일반검진 (GENERAL)</option>
                            <option value="SPECIAL">특수검진 (SPECIAL)</option>
                            <option value="OTHER">기타 (OTHER)</option>
                          </select>
                        </label>
                        <label className="staff-form-wide">
                          결과메모 (선택)
                          <textarea
                            value={healthFactForm.resultNote}
                            rows={3}
                            onChange={(event) =>
                              setHealthFactForm((current) => ({
                                ...current,
                                resultNote: event.target.value,
                              }))
                            }
                          />
                        </label>
                        {healthFieldErrors.check_date && (
                          <p className="staff-field-error staff-form-wide">
                            {healthFieldErrors.check_date}
                          </p>
                        )}
                        <div className="staff-form-actions staff-form-wide">
                          <button type="button" onClick={closeHealthFactForm}>
                            취소
                          </button>
                          <button
                            type="submit"
                            className="staff-button-primary"
                            disabled={healthMutationPending}
                          >
                            {healthMutationPending ? '저장 중…' : '검진사실 저장'}
                          </button>
                        </div>
                      </form>
                    )}

                    {healthFactsQuery.isLoading && (
                      <p className="staff-state">검진사실을 불러오는 중…</p>
                    )}
                    {healthFactsQuery.isError && (
                      <p className="staff-state staff-state-error" role="alert">
                        {healthQueryErrorMessage(healthFactsQuery.error)}
                      </p>
                    )}
                    {!healthFactsQuery.isLoading &&
                      !healthFactsQuery.isError &&
                      healthFacts.length === 0 && (
                        <p className="staff-state">등록된 검진이 없습니다.</p>
                      )}
                    <div className="staff-health-fact-list">
                      {healthFacts.map((fact) => (
                        <article
                          className="staff-health-fact-row"
                          data-testid="health-check-fact-row"
                          key={fact.id}
                        >
                          <div>
                            <strong>{fact.check_date}</strong>
                            <span>
                              {fact.check_type_code ?? '검진 유형 미등록'}
                              {fact.employment_id !== null
                                ? ` · 재직 #${fact.employment_id}`
                                : ' · 재직 미선택'}
                            </span>
                            {fact.result_note && <span>{fact.result_note}</span>}
                          </div>
                          {canManage && (
                            <div className="staff-row-actions">
                              <button type="button" onClick={() => openHealthFactEdit(fact)}>
                                검진사실 수정
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setHealthFactInvalidateTarget(fact);
                                  setActionError(null);
                                  setHealthFieldErrors({});
                                }}
                              >
                                검진사실 무효화
                              </button>
                            </div>
                          )}
                        </article>
                      ))}
                    </div>
                    {healthFactInvalidateTarget && (
                      <div className="staff-confirm-panel" role="alertdialog" aria-label="검진사실 무효화 확인">
                        <p>선택한 검진사실을 무효화하시겠습니까?</p>
                        <div className="staff-form-actions">
                          <button
                            type="button"
                            onClick={() => setHealthFactInvalidateTarget(null)}
                            disabled={healthMutationPending}
                          >
                            취소
                          </button>
                          <button
                            type="button"
                            className="staff-button-primary"
                            onClick={confirmHealthFactInvalidate}
                            disabled={healthMutationPending}
                          >
                            {healthMutationPending ? '처리 중…' : '검진사실 무효화 확정'}
                          </button>
                        </div>
                      </div>
                    )}
                  </section>

                  <section
                    className="staff-health-ledger"
                    aria-label="대상별 상태"
                    data-testid="staff-health-check-requirements-panel"
                  >
                    <div className="staff-health-ledger-heading">
                      <div>
                        <h4>대상별 상태</h4>
                        <p>기존에 부여된 대상의 상태와 조건부 근거를 관리합니다.</p>
                      </div>
                    </div>
                    {healthRequirementsQuery.isLoading && (
                      <p className="staff-state">대상별 상태 조회 중…</p>
                    )}
                    {healthRequirementsQuery.isError && (
                      <p className="staff-state staff-state-error" role="alert">
                        대상별 상태 조회 실패
                      </p>
                    )}
                    {!healthRequirementsQuery.isLoading &&
                      !healthRequirementsQuery.isError &&
                      healthRequirements.length === 0 && (
                        <p className="staff-state">등록된 대상별 상태가 없습니다.</p>
                      )}
                    <div className="staff-health-requirement-list">
                      {healthRequirements.map((requirement) => {
                        const draft = healthRequirementDrafts[requirement.id] ?? {
                          status: requirement.status,
                          healthCheckId:
                            requirement.health_check_id === null
                              ? ''
                              : String(requirement.health_check_id),
                          exemptReasonText: requirement.exempt_reason_text ?? '',
                        };
                        const selectedFact = healthFacts.find(
                          (fact) => String(fact.id) === draft.healthCheckId,
                        );
                        return (
                          <article
                            className="staff-health-requirement-row"
                            data-testid="health-check-requirement-row"
                            key={requirement.id}
                          >
                            <div className="staff-health-requirement-summary">
                              <strong>{requirement.target_key}</strong>
                              <span>규칙 버전 {requirement.target_rule_version_code}</span>
                              <span>
                                {requirement.employment_id === null
                                  ? '재직 범위 없음'
                                  : `재직 #${requirement.employment_id}`}
                              </span>
                            </div>
                            <div
                              className="staff-health-status-badge"
                              data-testid={`health-status-${draft.status}`}
                              data-health-check-id={
                                draft.status === 'COMPLETE' && draft.healthCheckId
                                  ? draft.healthCheckId
                                  : undefined
                              }
                              data-exempt-reason={
                                draft.status === 'EXEMPT' && draft.exemptReasonText
                                  ? draft.exemptReasonText
                                  : undefined
                              }
                            >
                              {draft.status}
                              {draft.status === 'EXEMPT' && draft.exemptReasonText && (
                                <span className="staff-health-inline-note">
                                  {draft.exemptReasonText}
                                </span>
                              )}
                            </div>
                            {canManage ? (
                              <div className="staff-health-requirement-controls">
                                <label>
                                  상태
                                  <select
                                    aria-label="상태"
                                    value={draft.status}
                                    disabled={healthMutationPending}
                                    onChange={(event) =>
                                      updateHealthRequirementDraft(requirement, {
                                        status: event.target.value as HealthCheckRequirementStatus,
                                      })
                                    }
                                  >
                                    <option value="COMPLETE">COMPLETE</option>
                                    <option value="INCOMPLETE">INCOMPLETE</option>
                                    <option value="EXEMPT">EXEMPT</option>
                                  </select>
                                </label>
                                {draft.status === 'COMPLETE' && (
                                  <label>
                                    완료 검진사실
                                    <select
                                      aria-label="완료 검진사실"
                                      value={draft.healthCheckId}
                                      disabled={healthMutationPending}
                                      onChange={(event) =>
                                        updateHealthRequirementDraft(requirement, {
                                          healthCheckId: event.target.value,
                                        })
                                      }
                                    >
                                      <option value="">선택</option>
                                      {healthFacts.map((fact) => (
                                        <option key={fact.id} value={fact.id}>
                                          {fact.check_date} · {fact.result_note ?? '결과메모 없음'}
                                        </option>
                                      ))}
                                    </select>
                                    {selectedFact && (
                                      <span className="staff-health-inline-note">
                                        선택된 사실 #{selectedFact.id}
                                      </span>
                                    )}
                                  </label>
                                )}
                                {draft.status === 'EXEMPT' && (
                                  <label>
                                    면제사유
                                    <textarea
                                      aria-label="면제사유"
                                      rows={2}
                                      value={draft.exemptReasonText}
                                      disabled={healthMutationPending}
                                      onChange={(event) =>
                                        updateHealthRequirementDraft(requirement, {
                                          exemptReasonText: event.target.value,
                                        })
                                      }
                                    />
                                  </label>
                                )}
                                {healthFieldErrors.health_check_id && draft.status === 'COMPLETE' && (
                                  <p className="staff-field-error">
                                    {healthFieldErrors.health_check_id}
                                  </p>
                                )}
                                {healthFieldErrors.exempt_reason_text && draft.status === 'EXEMPT' && (
                                  <p className="staff-field-error">
                                    {healthFieldErrors.exempt_reason_text}
                                  </p>
                                )}
                                <div className="staff-row-actions">
                                  <button
                                    type="button"
                                    onClick={() => submitHealthRequirement(requirement)}
                                    disabled={healthMutationPending}
                                  >
                                    상태 저장
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setHealthRequirementInvalidateTarget(requirement);
                                      setActionError(null);
                                      setHealthFieldErrors({});
                                    }}
                                    disabled={healthMutationPending}
                                  >
                                    대상별 상태 무효화
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div className="staff-health-requirement-readonly">
                                {draft.status === 'COMPLETE' && draft.healthCheckId && (
                                  <span>검진사실 #{draft.healthCheckId}</span>
                                )}
                                {draft.status === 'EXEMPT' && draft.exemptReasonText && (
                                  <span>면제사유: {draft.exemptReasonText}</span>
                                )}
                              </div>
                            )}
                          </article>
                        );
                      })}
                    </div>
                    {healthRequirementInvalidateTarget && (
                      <div
                        className="staff-confirm-panel"
                        role="alertdialog"
                        aria-label="대상별 상태 무효화 확인"
                      >
                        <p>선택한 대상별 상태를 무효화하시겠습니까?</p>
                        <div className="staff-form-actions">
                          <button
                            type="button"
                            onClick={() => setHealthRequirementInvalidateTarget(null)}
                            disabled={healthMutationPending}
                          >
                            취소
                          </button>
                          <button
                            type="button"
                            className="staff-button-primary"
                            onClick={confirmHealthRequirementInvalidate}
                            disabled={healthMutationPending}
                          >
                            {healthMutationPending ? '처리 중…' : '대상별 상태 무효화 확정'}
                          </button>
                        </div>
                      </div>
                    )}
                  </section>
                </section>
              )}

              {selectedTab === 'consultation' && (
                <section
                  className="staff-quarterly-consultation-panel"
                  data-testid="staff-quarterly-consultation-panel"
                >
                  <div className="staff-section-heading">
                    <div>
                      <h3>분기상담</h3>
                      <p>직원·연도·분기별 상담 사실과 상태를 관리합니다.</p>
                    </div>
                    {canManage && quarterlyConsultationForm.mode === null && (
                      <button
                        type="button"
                        data-testid="quarterly-consultation-add"
                        onClick={openQuarterlyConsultationCreate}
                      >
                        분기상담 추가
                      </button>
                    )}
                  </div>

                  {canManage && quarterlyConsultationForm.mode === 'create' && (
                    <form
                      className="staff-form staff-quarterly-consultation-form"
                      data-testid="quarterly-consultation-create-form"
                      onSubmit={submitQuarterlyConsultation}
                    >
                      <h4 className="staff-form-title">분기상담 추가</h4>
                      {renderQuarterlyConsultationFields(true)}
                      <div className="staff-form-actions staff-form-wide">
                        <button type="button" onClick={closeQuarterlyConsultationForm}>
                          취소
                        </button>
                        <button
                          type="submit"
                          className="staff-button-primary"
                          disabled={consultationMutationPending}
                        >
                          {consultationMutationPending ? '저장 중…' : '분기상담 저장'}
                        </button>
                      </div>
                    </form>
                  )}

                  {canManage && quarterlyConsultationForm.mode === 'replace' && (
                    <form
                      className="staff-form staff-quarterly-consultation-form"
                      data-testid="quarterly-consultation-replace-form"
                      onSubmit={submitQuarterlyConsultation}
                    >
                      <h4 className="staff-form-title">분기상담 무효화</h4>
                      <p className="staff-quarterly-consultation-replace-note">
                        선택한 행을 무효화하고 같은 연도·분기의 새 상태를 저장합니다.
                      </p>
                      {renderQuarterlyConsultationFields(false)}
                      <div className="staff-form-actions staff-form-wide">
                        <button type="button" onClick={closeQuarterlyConsultationForm}>
                          취소
                        </button>
                        <button
                          type="submit"
                          className="staff-button-primary"
                          disabled={consultationMutationPending}
                        >
                          {consultationMutationPending ? '처리 중…' : '무효화 확정'}
                        </button>
                      </div>
                    </form>
                  )}

                  {quarterlyConsultationsQuery.isLoading && (
                    <p className="staff-state">분기상담을 불러오는 중…</p>
                  )}
                  {quarterlyConsultationsQuery.isError && (
                    <p className="staff-state staff-state-error" role="alert">
                      {consultationQueryErrorMessage(quarterlyConsultationsQuery.error)}
                    </p>
                  )}
                  {!quarterlyConsultationsQuery.isLoading &&
                    !quarterlyConsultationsQuery.isError &&
                    quarterlyConsultations.length === 0 && (
                      <p className="staff-state">등록된 분기상담이 없습니다.</p>
                    )}

                  <div className="staff-quarterly-consultation-list">
                    {quarterlyConsultations.map((consultation) => {
                      const editing =
                        canManage &&
                        quarterlyConsultationForm.mode === 'edit' &&
                        quarterlyConsultationForm.editing?.id === consultation.id;
                      return (
                        <article
                          className="staff-quarterly-consultation-row"
                          data-testid="quarterly-consultation-row"
                          data-status={consultation.status}
                          key={consultation.id}
                        >
                          <div className="staff-quarterly-consultation-summary">
                            <strong>{consultation.calendar_year}</strong>
                            <span>{consultation.quarter_no}분기</span>
                            <span className="staff-quarterly-consultation-status">
                              {consultation.status}
                            </span>
                          </div>

                          {editing ? (
                            <form
                              className="staff-quarterly-consultation-inline-form"
                              onSubmit={submitQuarterlyConsultation}
                            >
                              {renderQuarterlyConsultationFields(false)}
                              <div className="staff-form-actions staff-form-wide">
                                <button
                                  type="button"
                                  onClick={closeQuarterlyConsultationForm}
                                >
                                  취소
                                </button>
                                <button
                                  type="submit"
                                  className="staff-button-primary"
                                  disabled={consultationMutationPending}
                                >
                                  {consultationMutationPending ? '저장 중…' : '저장'}
                                </button>
                              </div>
                            </form>
                          ) : (
                            <div className="staff-quarterly-consultation-fields">
                              {consultation.status === 'COMPLETE' && (
                                quarterlyConsultationForm.mode !== null ? (
                                  <div className="staff-quarterly-consultation-readonly-summary">
                                    <span>상담일 {consultation.counseling_date ?? '미등록'}</span>
                                    <span>처리내용 {consultation.content ?? '미등록'}</span>
                                  </div>
                                ) : (
                                  <>
                                    <label>
                                      상담일
                                      <input
                                        aria-label="상담일"
                                        type="date"
                                        value={consultation.counseling_date ?? ''}
                                        readOnly
                                      />
                                    </label>
                                    <label className="staff-form-wide">
                                      처리내용
                                      <textarea
                                        aria-label="처리내용"
                                        rows={3}
                                        value={consultation.content ?? ''}
                                        readOnly
                                      />
                                    </label>
                                  </>
                                )
                              )}
                              {consultation.status === 'INCOMPLETE' && (
                                quarterlyConsultationForm.mode !== null ? (
                                  <div className="staff-quarterly-consultation-readonly-summary">
                                    <span>
                                      미완료 사유 {consultation.incomplete_reason_text ?? '미등록'}
                                    </span>
                                  </div>
                                ) : (
                                  <label className="staff-form-wide">
                                    미완료 사유
                                    <textarea
                                      aria-label="미완료 사유"
                                      rows={3}
                                      value={consultation.incomplete_reason_text ?? ''}
                                      readOnly
                                    />
                                  </label>
                                )
                              )}
                              {consultation.status === 'EXEMPT' && (
                                quarterlyConsultationForm.mode !== null ? (
                                  <div className="staff-quarterly-consultation-readonly-summary">
                                    <span>
                                      면제 사유 {consultation.exempt_reason_text ?? '미등록'}
                                    </span>
                                  </div>
                                ) : (
                                  <label className="staff-form-wide">
                                    면제 사유
                                    <textarea
                                      aria-label="면제 사유"
                                      rows={3}
                                      value={consultation.exempt_reason_text ?? ''}
                                      readOnly
                                    />
                                  </label>
                                )
                              )}
                              {canManage && (
                                <div className="staff-row-actions staff-form-wide">
                                  <button
                                    type="button"
                                    onClick={() => openQuarterlyConsultationEdit(consultation)}
                                  >
                                    수정
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => openQuarterlyConsultationReplace(consultation)}
                                  >
                                    무효화
                                  </button>
                                </div>
                              )}
                            </div>
                          )}
                        </article>
                      );
                    })}
                  </div>

                  {quarterlyConsultationInvalidateTarget &&
                    quarterlyConsultationForm.mode !== 'replace' && (
                      <div className="staff-confirm-panel" role="alertdialog">
                        <p>선택한 분기상담을 무효화하시겠습니까?</p>
                        <button
                          type="button"
                          onClick={closeQuarterlyConsultationForm}
                        >
                          취소
                        </button>
                      </div>
                    )}
                </section>
              )}
            </>
          )}
        </section>
      </section>

      {createOpen && (
        <div className="staff-modal-backdrop" role="presentation">
          <section className="staff-modal" role="dialog" aria-modal="true">
            <div className="staff-modal-heading">
              <div>
                <p className="staff-eyebrow">원자 등록</p>
                <h2>신규 직원 등록</h2>
              </div>
              <button type="button" onClick={() => setCreateOpen(false)}>
                취소
              </button>
            </div>
            <form className="staff-form" onSubmit={submitCreate}>
              <label>
                성명
                <input name="name" required autoFocus />
              </label>
              <label>
                표시명
                <input name="display_name" />
              </label>
              <label>
                생년월일
                <input name="birth_date" type="date" required />
              </label>
              <label>
                성별
                <select name="sex_code" defaultValue="MALE" required>
                  <option value="MALE">남성</option>
                  <option value="FEMALE">여성</option>
                </select>
              </label>
              <label>
                주민등록번호
                <input
                  name="resident_number"
                  inputMode="numeric"
                  autoComplete="off"
                  required
                />
              </label>
              <label>
                전화번호
                <input name="phone" />
              </label>
              <label className="staff-form-wide">
                주소
                <input name="address" />
              </label>
              <label>
                입사일
                <input name="start_date" type="date" required />
              </label>
              <label className="staff-form-wide">
                메모
                <textarea name="memo" rows={3} />
              </label>
              <div className="staff-form-actions staff-form-wide">
                <button type="button" onClick={() => setCreateOpen(false)}>
                  취소
                </button>
                <button
                  type="submit"
                  className="staff-button-primary"
                  disabled={createMutation.isPending}
                >
                  {createMutation.isPending ? '등록 중…' : '등록'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {closeOpen && activeEmployment && (
        <div className="staff-modal-backdrop" role="presentation">
          <section className="staff-modal staff-modal-compact" role="dialog" aria-modal="true">
            <div className="staff-modal-heading">
              <h2>재직 종료</h2>
              <button type="button" onClick={() => setCloseOpen(false)}>
                취소
              </button>
            </div>
            <form className="staff-form staff-form-single" onSubmit={submitClose}>
              <label>
                퇴사일
                <input name="end_date" type="date" required />
              </label>
              <label>
                종료 사유 코드
                <input name="end_reason_code" defaultValue="EMPLOYMENT_ENDED" />
              </label>
              <div className="staff-form-actions">
                <button type="button" onClick={() => setCloseOpen(false)}>
                  취소
                </button>
                <button
                  type="submit"
                  className="staff-button-primary"
                  disabled={closeMutation.isPending}
                >
                  종료 확정
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {rehireOpen && detail && (
        <div className="staff-modal-backdrop" role="presentation">
          <section className="staff-modal staff-modal-compact" role="dialog" aria-modal="true">
            <div className="staff-modal-heading">
              <h2>재입사</h2>
              <button type="button" onClick={() => setRehireOpen(false)}>
                취소
              </button>
            </div>
            <form className="staff-form staff-form-single" onSubmit={submitRehire}>
              <label>
                재입사일
                <input name="start_date" type="date" required />
              </label>
              <div className="staff-form-actions">
                <button type="button" onClick={() => setRehireOpen(false)}>
                  취소
                </button>
                <button
                  type="submit"
                  className="staff-button-primary"
                  disabled={rehireMutation.isPending}
                >
                  재입사 등록
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {revealOpen && detail && (
        <div className="staff-modal-backdrop" role="presentation">
          <section className="staff-modal staff-modal-compact" role="dialog" aria-modal="true">
            <div className="staff-modal-heading">
              <div>
                <p className="staff-eyebrow">민감정보 단계 인증</p>
                <h2>주민등록번호 조회</h2>
              </div>
              <button type="button" onClick={closeReveal}>
                닫기
              </button>
            </div>
            <p className="staff-sensitive-warning">
              업무상 필요한 경우에만 조회하세요. 성공한 조회는 접근기록에 남습니다.
            </p>
            {!revealedResidentNumber ? (
              <form className="staff-form staff-form-single" onSubmit={submitReveal}>
                <label>
                  현재 PIN
                  <input
                    type="password"
                    inputMode="numeric"
                    autoComplete="off"
                    placeholder="현재 PIN"
                    value={currentPin}
                    onChange={(event) => setCurrentPin(event.target.value)}
                    required
                  />
                </label>
                <div className="staff-form-actions">
                  <button type="button" onClick={closeReveal}>
                    닫기
                  </button>
                  <button
                    type="submit"
                    className="staff-button-primary"
                    disabled={isRevealPending}
                  >
                    {isRevealPending ? '확인 중…' : '조회'}
                  </button>
                </div>
              </form>
            ) : (
              <div className="staff-revealed-value">
                <span>조회 결과</span>
                <strong data-testid="revealed-rrn">{revealedResidentNumber}</strong>
                <button type="button" onClick={closeReveal}>
                  닫기
                </button>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
};

export default StaffPage;
