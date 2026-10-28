import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { DISK_TYPE, formatDataUnits, formatNumber } from "../format";
import type { Disk, Thresholds } from "../types";
import { effectiveSample } from "./storage";
import { EmptyState } from "./ui";

type Zone = { from: number; to: number; tone: "ok" | "info" | "warning" | "critical"; label: string };
type Scale = { min: number; max: number; zones: Zone[]; unit: string };

// Statusne boje (rezervisane za stanje, nikad za seriju) - uvek uz tekstualnu oznaku zone.
const ZONE_COLOR: Record<Zone["tone"], string> = {
  ok: "#0ca30c",
  info: "#2a78d6",
  warning: "#fab219",
  critical: "#d03b3b",
};

/** Opseg i zone merača za metriku i tip diska, iz trenutnih pragova alarma. */
function scaleFor(metric: string, disk: Disk, th: Thresholds | undefined, value: number): Scale | null {
  if (metric === "temperature_c") {
    const kind = disk.disk_type === "nvme" ? "nvme" : disk.disk_type === "ssd" ? "ssd" : "hdd";
    const t = th?.temperature[kind] ?? { info: 47, warning: 50, critical: 55 };
    return {
      min: 0, max: Math.max(t.critical + 15, value + 5), unit: "°C",
      zones: [
        { from: 0, to: t.info, tone: "ok", label: "normalno" },
        { from: t.info, to: t.warning, tone: "info", label: "blizu praga" },
        { from: t.warning, to: t.critical, tone: "warning", label: "iznad praga" },
        { from: t.critical, to: Math.max(t.critical + 15, value + 5), tone: "critical", label: "kritično" },
      ],
    };
  }
  if (metric === "percentage_used") {
    const p = th?.percentage_used ?? { warning: 80, high: 90, critical: 100 };
    return { min: 0, max: 100, unit: "%", zones: [
      { from: 0, to: p.warning, tone: "ok", label: "normalno habanje" },
      { from: p.warning, to: p.high, tone: "warning", label: "upozorenje" },
      { from: p.high, to: 100, tone: "critical", label: "visoko" },
    ] };
  }
  if (metric === "ssd_life_left" || metric === "available_spare") {
    const low = metric === "ssd_life_left" ? th?.ssd_life_left.high ?? 10 : (th?.available_spare_min as number) ?? 10;
    const warn = metric === "ssd_life_left" ? th?.ssd_life_left.warning ?? 20 : low * 2;
    return { min: 0, max: 100, unit: "%", zones: [
      { from: 0, to: low, tone: "critical", label: "kritično nisko" },
      { from: low, to: warn, tone: "warning", label: "upozorenje" },
      { from: warn, to: 100, tone: "ok", label: "dovoljno" },
    ] };
  }
  if (["reallocated_sectors", "pending_sectors", "uncorrectable_sectors", "media_errors", "crc_errors"].includes(metric)) {
    const max = Math.max(10, Math.ceil(value * 1.5));
    return { min: 0, max, unit: "", zones: [
      { from: 0, to: 0.5, tone: "ok", label: "bez grešaka" },
      { from: 0.5, to: max, tone: metric === "crc_errors" ? "info" : "warning", label: metric === "crc_errors" ? "greške veze" : "ima grešaka" },
    ] };
  }
  if (metric === "power_on_hours") {
    const max = Math.max(60_000, Math.ceil(value / 10_000) * 10_000);
    return { min: 0, max, unit: "h", zones: [
      { from: 0, to: 35_000, tone: "ok", label: "do ~4 godine" },
      { from: 35_000, to: 50_000, tone: "info", label: "zreo disk" },
      { from: 50_000, to: max, tone: "warning", label: "preko 50.000 h" },
    ] };
  }
  return null;
}

function polar(cx: number, cy: number, r: number, frac: number) {
  const a = Math.PI * (1 - frac);
  return [cx + r * Math.cos(a), cy - r * Math.sin(a)];
}

function arc(cx: number, cy: number, r: number, f0: number, f1: number) {
  const [x0, y0] = polar(cx, cy, r, f0);
  const [x1, y1] = polar(cx, cy, r, f1);
  // Luk merača je najviše polukrug, pa je oznaka „large-arc” uvek 0.
  return `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1}`;
}

function Gauge({ value, scale, display }: { value: number; scale: Scale; display: string }) {
  const span = scale.max - scale.min || 1;
  const frac = Math.min(1, Math.max(0, (value - scale.min) / span));
  const zone = scale.zones.find((z) => value >= z.from && value < z.to) ?? scale.zones[scale.zones.length - 1];
  const [nx, ny] = polar(60, 60, 44, frac);
  return (
    <svg viewBox="0 0 120 72" className="w-full max-w-48" role="img" aria-label={`${display}, ${zone.label}`}>
      {/* zone: tanki luk u boji statusa, 2 px razmak između zona */}
      {scale.zones.map((z) => {
        const a = Math.max(0, (z.from - scale.min) / span);
        const b = Math.min(1, (z.to - scale.min) / span);
        if (b <= a) return null;
        return <path key={z.label} d={arc(60, 60, 50, a + 0.006, b - 0.006)} stroke={ZONE_COLOR[z.tone]} strokeWidth={6} fill="none" opacity={0.85} />;
      })}
      {/* trenutna vrednost: luk od nule do vrednosti + kazaljka */}
      <path d={arc(60, 60, 40, 0, Math.max(0.001, frac))} stroke="var(--chart-axis)" strokeWidth={3} fill="none" strokeLinecap="round" opacity={0.5} />
      <line x1={60} y1={60} x2={nx} y2={ny} stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
      <circle cx={60} cy={60} r={4} fill="currentColor" stroke="var(--chart-surface)" strokeWidth={2} />
    </svg>
  );
}

/** Merači po disku (spec. §10.5, dodatni prikaz): trenutna vrednost izabrane metrike sa zonama po pragovima. */
export default function DiskGauges({ disks, metric, metricLabel }: { disks: Disk[]; metric: string; metricLabel: string }) {
  const th = useQuery({ queryKey: ["thresholds"], queryFn: () => api<Thresholds>("/thresholds") });
  const items = disks
    .map((d) => {
      const s = effectiveSample(d);
      const raw = s ? (s as unknown as Record<string, number | null>)[metric] : null;
      return { d, value: raw ?? null };
    })
    .filter((x) => x.value != null);
  if (items.length === 0) return <EmptyState>Nijedan disk ne prijavljuje „{metricLabel}”.</EmptyState>;
  const supported = scaleFor(metric, items[0].d, th.data, items[0].value!) !== null || metric === "data_units_written";
  return (
    <div className="space-y-2">
      {!supported && <p className="text-sm text-slate-500">Za ovu metriku merač prikazuje trenutnu vrednost bez zona.</p>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {items.map(({ d, value }) => {
          const v = value as number;
          const scale = scaleFor(metric, d, th.data, v) ?? { min: 0, max: Math.max(1, v * 1.25), unit: "", zones: [{ from: 0, to: Math.max(1, v * 1.25), tone: "info" as const, label: "vrednost" }] };
          const zone = scale.zones.find((z) => v >= z.from && v < z.to) ?? scale.zones[scale.zones.length - 1];
          const display = metric === "data_units_written" ? formatDataUnits(v) : formatNumber(v, scale.unit ? (scale.unit === "%" ? "%" : ` ${scale.unit}`) : "");
          const standby = d.latest?.smart_health === "standby";
          return (
            <Link key={d.id} to={`/diskovi/${d.id}`} className="flex flex-col items-center rounded-xl border border-slate-200 bg-white p-3 text-center hover:border-brand-500 dark:border-slate-800 dark:bg-slate-900">
              <Gauge value={v} scale={scale} display={display} />
              <span className="-mt-1 text-xl font-semibold tabular-nums">{display}</span>
              <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
                <span className="inline-block size-2 rounded-full" style={{ background: ZONE_COLOR[zone.tone] }} aria-hidden />
                {zone.label}{standby ? " · standby (poslednje očitavanje)" : ""}
              </span>
              <span className="mt-1 w-full truncate text-xs font-medium" title={`${d.device_name} · ${d.device_path} · ${d.model ?? ""}`}>{d.model ?? d.device_path}</span>
              <span className="w-full truncate text-[11px] text-slate-500">{d.device_name} · {d.device_path} · {DISK_TYPE[d.disk_type]}</span>
            </Link>
          );
        })}
      </div>
      <p className="text-xs text-slate-500">Merači prikazuju poslednje očitavanje; zone dolaze iz pragova alarma (Podešavanja → Pragovi). Za istoriju izaberite prikaz „Grafikon”.</p>
    </div>
  );
}
