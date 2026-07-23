export const BEIJING_TIME_ZONE = "Asia/Shanghai";

const TIMEZONE_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export interface BeijingDateTimeParts {
  year: string;
  month: string;
  day: string;
  hour: string;
  minute: string;
}

function parseApiDateTime(value: string): Date {
  const normalized = TIMEZONE_SUFFIX.test(value) ? value : `${value}Z`;
  return new Date(normalized);
}

export function formatBeijingDateTime(value: string): string {
  const date = parseApiDateTime(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString("zh-CN", { timeZone: BEIJING_TIME_ZONE });
}

export function formatBeijingDate(value: string): string {
  const date = parseApiDateTime(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString("zh-CN", { timeZone: BEIJING_TIME_ZONE });
}

export function formatBeijingTime(value: string): string {
  const date = parseApiDateTime(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleTimeString("zh-CN", {
      timeZone: BEIJING_TIME_ZONE,
      hour12: false
    });
}

export function beijingDateTimeParts(date = new Date()): BeijingDateTimeParts {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    year: values.year,
    month: values.month,
    day: values.day,
    hour: values.hour,
    minute: values.minute
  };
}
