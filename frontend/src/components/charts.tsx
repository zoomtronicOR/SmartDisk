import { Download, Table2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Brush, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts";
import { formatBytes, formatDateTime, formatNumber } from "../format";
import { Button, EmptyState, Select, Table, Td } from "./ui";

export const SERIES_COLORS = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);

export type Point = { t: string; value: number | null; min: number | null; max: number | null; n: number };
export type Series = { id: number; label: string; points: Point[]; color?: string };

const colorOf = (s: Series, i: number) => s.color ?? SERIES_COLORS[i];

/** Formatira vrednost metrike po jedinici (bajtovi, procenti, sati…). */
export function formatMetric(value: number | null | undefined, unit: string): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (unit === "B") return formatBytes(value);
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 10) / 10;
  return formatNumber(rounded, unit ? (unit === "%" ? "%" : ` ${unit}`) : "");
}

function compactTick(value: number, unit: string): string {
  if (unit === "B") return formatBytes(value);
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} mlrd`;
  if (abs >= 1e6) return `${(value / 1e6).toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} mil`;
  if (abs >= 1e4) return `${(value / 1e3).toLocaleString("sr-Latn", { maximumFractionDigits: 0 })} hilj`;
  return value.toLocaleString("sr-Latn", { maximumFractionDigits: 1 });
}

function tickTime(ts: number, spanMs: number): string {
  const d = new Date(ts);
  const opts: Intl.DateTimeFormatOptions =
    spanMs <= 2 * 86400_000 ? { hour: "2-digit", minute: "2-digit" } : spanMs <= 120 * 86400_000 ? { day: "2-digit", month: "2-digit" } : { month: "2-digit", year: "2-digit" };
  return new Intl.DateTimeFormat("sr-Latn-RS", opts).format(d);
}

type Row = { ts: number } & Record<string, number | null>;

function ChartTooltip({ active, payload, label, series, unit }: TooltipProps<number, string> & { series: Series[]; unit: string }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="mb-1 text-slate-500">{formatDateTime(new Date(label as number).toISOString())}</p>
      {series.map((s, i) => {
        const item = payload.find((p) => p.dataKey === `s${s.id}`);
        if (!item || item.value == null) return null;
        const extra = (item.payload as Row)[`r${s.id}`];
        return (
          <div key={s.id} className="flex items-center gap-2">
            <span className="inline-block h-0.5 w-3 rounded" style={{ background: colorOf(s, i) }} aria-hidden />
            <span className="font-semibold">{formatMetric(item.value as number, unit)}</span>
            {extra != null && <span className="text-slate-500">(raspon {String(extra)})</span>}
            {series.length > 1 && <span className="max-w-64 truncate text-slate-500">{s.label}</span>}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Linijski grafikon kroz vreme: 2px linije, tooltip sa svim serijama na istom trenutku,
 * legenda za 2+ serije, zumiranje prevlačenjem donje trake (Brush) i prikaz kao tabela.
 */
export function TimeChart({
  series,
  unit,
  height = 280,
  exportHref,
  emptyText = "Nema podataka za izabrani period.",
  title,
  markers = [],
}: {
  /** Vertikalne oznake (npr. trenutak kada je alarm prvi put detektovan). */
  markers?: { ts: number; label: string }[];
  series: Series[];
  unit: string;
  height?: number;
  exportHref?: (format: "csv" | "xlsx") => string;
  emptyText?: string;
  title?: ReactNode;
}) {
  const [tableView, setTableView] = useState(false);
  const { rows, span } = useMemo(() => {
    const map = new Map<number, Row>();
    for (const s of series) {
      for (const p of s.points) {
        const ts = new Date(p.t).getTime();
        const row = map.get(ts) ?? ({ ts } as Row);
        row[`s${s.id}`] = p.value;
        if (p.n > 1 && p.min != null && p.max != null && p.min !== p.max) {
          (row as Record<string, unknown>)[`r${s.id}`] = `${formatMetric(p.min, unit)} – ${formatMetric(p.max, unit)}`;
        }
        map.set(ts, row);
      }
    }
    const sorted = [...map.values()].sort((a, b) => a.ts - b.ts);
    return { rows: sorted, span: sorted.length > 1 ? sorted[sorted.length - 1].ts - sorted[0].ts : 0 };
  }, [series, unit]);

  const hasData = rows.length > 0;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium">{title}</div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" icon={<Table2 className="size-4" />} onClick={() => setTableView(!tableView)} aria-pressed={tableView}>
            {tableView ? "Grafikon" : "Tabela"}
          </Button>
          {exportHref && hasData && (
            <>
              <a href={exportHref("csv")} download className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
                <Download className="size-4" /> CSV
              </a>
              <a href={exportHref("xlsx")} download className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
                <Download className="size-4" /> XLSX
              </a>
            </>
          )}
        </div>
      </div>
      {!hasData ? (
        <EmptyState>{emptyText}</EmptyState>
      ) : tableView ? (
        <div className="max-h-96 overflow-auto">
          <Table head={["Vreme", ...series.map((s) => s.label)]}>
            {[...rows].reverse().map((r) => (
              <tr key={r.ts}>
                <Td className="whitespace-nowrap">{formatDateTime(new Date(r.ts).toISOString())}</Td>
                {series.map((s) => (
                  <Td key={s.id}>{formatMetric(r[`s${s.id}`], unit)}</Td>
                ))}
              </tr>
            ))}
          </Table>
        </div>
      ) : (
        <>
          <div style={{ height }} role="img" aria-label={`Grafikon: ${series.map((s) => s.label).join(", ")}`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis
                  dataKey="ts"
                  type="number"
                  scale="time"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(v) => tickTime(v, span)}
                  stroke="var(--chart-axis)"
                  tick={{ fontSize: 11, fill: "var(--chart-axis)" }}
                  tickLine={false}
                  minTickGap={40}
                />
                <YAxis
                  width={64}
                  stroke="var(--chart-axis)"
                  tick={{ fontSize: 11, fill: "var(--chart-axis)" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => compactTick(v, unit)}
                  // Količine u bajtovima (zauzeće, upisano) počinju od nule; inače bi sitne promene izgledale kao skokovi.
                  domain={unit === "B" ? [0, "auto"] : ["auto", "auto"]}
                  allowDecimals={unit !== ""}
                />
                <Tooltip content={<ChartTooltip series={series} unit={unit} />} cursor={{ stroke: "var(--chart-axis)", strokeWidth: 1 }} />
                {series.map((s, i) => (
                  <Line
                    key={s.id}
                    type="monotone"
                    dataKey={`s${s.id}`}
                    name={s.label}
                    stroke={colorOf(s, i)}
                    strokeWidth={2}
                    dot={rows.length <= 2 ? { r: 4, strokeWidth: 2, stroke: "var(--chart-surface)", fill: colorOf(s, i) } : false}
                    activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--chart-surface)" }}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
                {markers
                  .filter((m) => rows.length > 0 && m.ts >= rows[0].ts && m.ts <= rows[rows.length - 1].ts)
                  .map((m) => (
                    <ReferenceLine key={`${m.ts}-${m.label}`} x={m.ts} stroke="var(--chart-axis)" strokeDasharray="0" strokeWidth={1}
                      label={{ value: "▲", position: "insideTopLeft", fill: "var(--chart-axis)", fontSize: 10 }} />
                  ))}
                {rows.length > 20 && (
                  <Brush dataKey="ts" height={22} stroke="var(--chart-axis)" fill="var(--chart-surface)" tickFormatter={(v) => tickTime(v, span)} travellerWidth={8} />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {series.length > 1 && (
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-300" aria-label="Legenda">
              {series.map((s, i) => (
                <li key={s.id} className="flex items-center gap-1.5">
                  <span className="inline-block h-0.5 w-4 rounded" style={{ background: colorOf(s, i) }} aria-hidden />
                  {s.label}
                </li>
              ))}
            </ul>
          )}
          {markers.length > 0 && (
            <ul className="text-xs text-slate-500" aria-label="Oznake na grafikonu">
              {markers.map((m) => (
                <li key={`${m.ts}-${m.label}`}>▲ {formatDateTime(new Date(m.ts).toISOString())} – {m.label}</li>
              ))}
            </ul>
          )}
          {rows.length > 20 && <p className="text-xs text-slate-500">Zumiranje: prevucite krajeve donje trake.</p>}
        </>
      )}
    </div>
  );
}

// --- Period ---

export type Bucket = "auto" | "raw" | "hour" | "day" | "week";
export type PeriodValue = { preset: string; from: string; to: string; bucket: Bucket };

export const PRESETS: { key: string; label: string; hours: number }[] = [
  { key: "24h", label: "24 sata", hours: 24 },
  { key: "7d", label: "7 dana", hours: 24 * 7 },
  { key: "30d", label: "30 dana", hours: 24 * 30 },
  { key: "90d", label: "90 dana", hours: 24 * 90 },
  { key: "1y", label: "1 godina", hours: 24 * 365 },
];

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function periodFromPreset(key: string, bucket: Bucket = "auto"): PeriodValue {
  const preset = PRESETS.find((p) => p.key === key) ?? PRESETS[1];
  const to = new Date();
  const from = new Date(to.getTime() - preset.hours * 3600_000);
  return { preset: preset.key, from: toLocalInput(from), to: toLocalInput(to), bucket };
}

/** Parametri za API: lokalno vreme iz pregledača sa njegovim UTC pomakom. */
export function periodQuery(p: PeriodValue): string {
  const iso = (v: string) => new Date(v).toISOString();
  return `from=${encodeURIComponent(iso(p.from))}&to=${encodeURIComponent(iso(p.to))}&bucket=${p.bucket}`;
}

export function PeriodPicker({ value, onChange, showBucket = true }: { value: PeriodValue; onChange: (v: PeriodValue) => void; showBucket?: boolean }) {
  const [custom, setCustom] = useState(value.preset === "custom");
  return (
    <div className="flex flex-wrap items-end gap-2" role="group" aria-label="Period">
      <div className="inline-flex flex-wrap rounded-lg border border-slate-300 bg-white p-0.5 dark:border-slate-600 dark:bg-slate-900">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            aria-pressed={value.preset === p.key && !custom}
            onClick={() => {
              setCustom(false);
              onChange(periodFromPreset(p.key, value.bucket));
            }}
            className={`rounded-md px-2.5 py-1 text-sm ${
              value.preset === p.key && !custom ? "bg-brand-700 font-medium text-white" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            }`}
          >
            {p.label}
          </button>
        ))}
        <button
          type="button"
          aria-pressed={custom}
          onClick={() => setCustom(true)}
          className={`rounded-md px-2.5 py-1 text-sm ${custom ? "bg-brand-700 font-medium text-white" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}
        >
          Od–do
        </button>
      </div>
      {custom && (
        <>
          <label className="text-xs text-slate-500">
            Od
            <input
              type="datetime-local"
              className="ml-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
              value={value.from}
              max={value.to}
              onChange={(e) => e.target.value && onChange({ ...value, preset: "custom", from: e.target.value })}
            />
          </label>
          <label className="text-xs text-slate-500">
            Do
            <input
              type="datetime-local"
              className="ml-1 rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
              value={value.to}
              min={value.from}
              onChange={(e) => e.target.value && onChange({ ...value, preset: "custom", to: e.target.value })}
            />
          </label>
        </>
      )}
      {showBucket && (
        <Select className="max-w-60 py-1" value={value.bucket} onChange={(e) => onChange({ ...value, bucket: e.target.value as Bucket })} aria-label="Interval agregacije">
          <option value="auto">Interval: automatski</option>
          <option value="raw">Sirovo (svako očitavanje)</option>
          <option value="hour">Satno</option>
          <option value="day">Dnevno</option>
          <option value="week">Nedeljno</option>
        </Select>
      )}
    </div>
  );
}

export const BUCKET_LABEL: Record<string, string> = { raw: "sirovo", hour: "satno", day: "dnevno", week: "nedeljno" };
