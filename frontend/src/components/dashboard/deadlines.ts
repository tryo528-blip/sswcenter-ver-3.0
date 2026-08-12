export interface DdayResult {
  /** D-3, D-DAY, D+2 등 */
  dday: string;
  /** M/D 형식 (연도 없음, 제로 패딩 없음) */
  actualDate: string;
}

/** YYYY-MM-DD ISO 문자열을 로컬 달력 기준으로 파싱한다 (UTC 영향 회피). */
function parseISODateLocal(iso: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) throw new Error(`Invalid date: ${iso}`);
  const y = Number(m[1]);
  const mo = Number(m[2]) - 1;
  const d = Number(m[3]);
  const date = new Date(y, mo, d);
  if (isNaN(date.getTime())) throw new Error(`Invalid date: ${iso}`);
  if (date.getFullYear() !== y || date.getMonth() !== mo || date.getDate() !== d) {
    throw new Error(`Invalid date: ${iso}`);
  }
  return date;
}

/**
 * 문자열 또는 Date를 로컬 자정(달력 날짜)으로 정규화한다.
 * 유효하지 않은 날짜이면 "Invalid date: …" 메시지와 함께 throw 한다.
 */
function toLocalMidnight(raw: string | Date): Date {
  if (raw instanceof Date) {
    if (isNaN(raw.getTime())) throw new Error(`Invalid date: ${String(raw)}`);
    return new Date(raw.getFullYear(), raw.getMonth(), raw.getDate());
  }
  // ISO 8601 날짜 전용 문자열은 로컬로 직접 파싱한다.
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return parseISODateLocal(raw);
  }
  // 그 외 문자열은 런타임 파싱 후 로컬 구성요소만 추출한다.
  const fallback = new Date(raw);
  if (isNaN(fallback.getTime())) throw new Error(`Invalid date: ${String(raw)}`);
  return new Date(fallback.getFullYear(), fallback.getMonth(), fallback.getDate());
}

/** Date → "M/D" (1월→1, 0 패딩 없음) */
function formatMD(d: Date): string {
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/** 순수 D-day 표시 계약 */
export function computeDday(today: string | Date, deadline: string | Date): DdayResult {
  const t = toLocalMidnight(today);
  const d = toLocalMidnight(deadline);

  const diffDays = Math.round((d.getTime() - t.getTime()) / 86_400_000);

  return {
    dday: diffDays === 0 ? 'D-DAY' : diffDays > 0 ? `D-${diffDays}` : `D+${-diffDays}`,
    actualDate: formatMD(d),
  };
}
