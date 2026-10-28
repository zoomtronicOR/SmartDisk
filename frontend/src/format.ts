import type { AlarmStatus, DeviceStatus, DiskState, DiskType, HealthLevel, Pool, Role, Run, Severity, SmartHealth } from "./types";

let timezone = "Europe/Belgrade";

export function setDisplayTimezone(tz: string) {
  timezone = tz;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso || Number.isNaN(new Date(iso).getTime())) return "-"; // neispravan datum ne sme da obori ekran
  return new Intl.DateTimeFormat("sr-Latn-RS", {
    timeZone: timezone,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso || Number.isNaN(new Date(iso).getTime())) return "-";
  const diff = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("sr-Latn", { numeric: "auto" });
  if (abs < 60) return rtf.format(diff, "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

export function formatInterval(minutes: number): string {
  if (minutes % 1440 === 0) return `${minutes / 1440} d`;
  if (minutes % 60 === 0) return `${minutes / 60} h`;
  return `${minutes} min`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "-";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} ${units[i]}`;
}

export function formatDuration(ms: number | null): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} s`;
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrator",
  operator: "Operater",
  viewer: "Pregled",
};

export const DEVICE_STATUS: Record<DeviceStatus, { label: string; tone: Tone }> = {
  ok: { label: "Dostupan", tone: "ok" },
  error: { label: "Greška", tone: "critical" },
  waiting: { label: "Čeka prvo prikupljanje", tone: "unknown" },
  disabled: { label: "Nadzor isključen", tone: "unknown" },
  not_configured: { label: "Nije podešen", tone: "warning" },
};

export const RUN_STATUS: Record<Run["status"], { label: string; tone: Tone }> = {
  success: { label: "Uspešno", tone: "ok" },
  partial: { label: "Delimično", tone: "warning" },
  failed: { label: "Neuspešno", tone: "critical" },
  running: { label: "U toku", tone: "info" },
};

export const RUN_TRIGGER: Record<Run["trigger"], string> = {
  scheduled: "Planirano",
  manual: "Ručno",
  test: "Test konekcije",
};

export type Tone = "ok" | "warning" | "critical" | "unknown" | "info";

export function formatNumber(value: number | null | undefined, suffix = ""): string {
  if (value == null) return "-";
  return `${value.toLocaleString("sr-Latn")}${suffix}`;
}

/** Sati rada: „34.565 h (3,9 god.)”. */
export function formatHours(hours: number | null | undefined): string {
  if (hours == null) return "-";
  const years = hours / 8766;
  return `${hours.toLocaleString("sr-Latn")} h` + (years >= 0.1 ? ` (${years.toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} god.)` : "");
}

/** Kapacitet diska se iskazuje decimalno, kao na nalepnici diska (8 TB, 1 TB). */
export function formatCapacity(bytes: number | null | undefined): string {
  if (bytes == null) return "-";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let value = bytes;
  let i = 0;
  while (value >= 1000 && i < units.length - 1) {
    value /= 1000;
    i++;
  }
  return `${value.toLocaleString("sr-Latn", { maximumFractionDigits: value < 10 ? 2 : 1 })} ${units[i]}`;
}

/** NVMe „data units” su po 512 000 bajtova. */
export function formatDataUnits(units: number | null | undefined): string {
  if (units == null) return "-";
  // Isto kao zauzeće i grafikoni (binarne jedinice), da se iste vrednosti ne razlikuju po ekranima.
  return formatBytes(units * 512_000);
}

export function maskSerial(serial: string | null): string {
  if (!serial) return "-";
  if (serial.length <= 4) return "••••";
  return "•".repeat(Math.min(serial.length - 4, 8)) + serial.slice(-4);
}

export const DISK_STATE: Record<DiskState, { label: string; tone: Tone }> = {
  ok: { label: "Bez upozorenja", tone: "ok" },
  warning: { label: "Upozorenje", tone: "warning" },
  critical: { label: "Kritično", tone: "critical" },
  unknown: { label: "Nema podataka", tone: "unknown" },
};

export const SMART_HEALTH: Record<SmartHealth, { label: string; tone: Tone }> = {
  passed: { label: "PASSED", tone: "ok" },
  failed: { label: "FAILED", tone: "critical" },
  unknown: { label: "Nepoznato", tone: "unknown" },
  unavailable: { label: "Nedostupan", tone: "unknown" },
  standby: { label: "Standby", tone: "info" },
};

export const DISK_TYPE: Record<DiskType, string> = {
  hdd: "HDD",
  ssd: "SSD",
  nvme: "NVMe",
  sas: "SAS",
  usb: "USB",
  unknown: "Nepoznat",
};

export const POOL_TECH: Record<Pool["technology"], string> = {
  zfs: "ZFS pool",
  lvm_thin: "LVM-thin",
  lvm_vg: "LVM volume grupa",
  mdadm: "Linux RAID (mdadm)",
  pve_storage: "Proxmox storage",
  synology_volume: "Synology volumen",
};

export function poolTone(pool: Pool): { label: string; tone: Tone } {
  if (!pool.is_present) return { label: "Nije pronađen", tone: "unknown" };
  if (pool.healthy === false) return { label: pool.status, tone: "critical" };
  if (pool.scan_state === "in_progress") return { label: `${pool.status} · ${SCAN_LABEL[pool.scan_type ?? ""] ?? "provera"} u toku`, tone: "info" };
  if (pool.healthy === null) return { label: pool.status, tone: "unknown" };
  return { label: pool.status, tone: "ok" };
}

export const SCAN_LABEL: Record<string, string> = {
  scrub: "Scrub",
  resilver: "Resilver",
  recovery: "Oporavak",
  resync: "Sinhronizacija",
  check: "Provera",
  reshape: "Preoblikovanje",
  repair: "Popravka",
};

export const SEVERITY: Record<Severity, { label: string; tone: Tone }> = {
  info: { label: "Informativno", tone: "info" },
  warning: { label: "Upozorenje", tone: "warning" },
  high: { label: "Visoko", tone: "critical" },
  critical: { label: "Kritično", tone: "critical" },
};

export const ALARM_STATUS: Record<AlarmStatus, { label: string; tone: Tone }> = {
  open: { label: "Otvoren", tone: "warning" },
  acknowledged: { label: "Potvrđen", tone: "info" },
  resolved: { label: "Rešen", tone: "ok" },
};

/** „Zdravlje diska” (spec. §8.8) - zaseban indikator, nezavisan od SMART statusa. */
export const HEALTH: Record<HealthLevel, { label: string; tone: Tone }> = {
  excellent: { label: "Odlično", tone: "ok" },
  good: { label: "Dobro", tone: "ok" },
  attention: { label: "Pažnja", tone: "warning" },
  endangered: { label: "Ugroženo", tone: "critical" },
  critical: { label: "Kritično", tone: "critical" },
  unknown: { label: "Nepoznato", tone: "unknown" },
};

export const HISTORY_ACTION: Record<string, string> = {
  opened: "Otvoren",
  escalated: "Pogoršanje (eskalacija)",
  deescalated: "Ublažen nivo",
  acknowledged: "Potvrđen",
  comment: "Komentar",
  resolved: "Rešen",
  reopened: "Ponovo otvoren",
};
