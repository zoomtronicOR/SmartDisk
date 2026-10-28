import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { formatDateTime } from "../format";
import type { Alarm, DiskTrends, DiskType, SeriesResponse } from "../types";
import { BUCKET_LABEL, PeriodPicker, TimeChart, formatMetric, periodFromPreset, periodQuery, type PeriodValue } from "./charts";
import { Card, EmptyState, ErrorText, Spinner, Table, Td } from "./ui";

/** Metrike koje imaju smisla za tip diska (NVMe nema sektore, SATA nema NVMe vrednosti). */
export function metricsFor(type: DiskType): { key: string; label: string }[] {
  const common = [
    { key: "temperature_c", label: "Temperatura" },
    { key: "power_on_hours", label: "Sati rada" },
    { key: "power_cycles", label: "Uključivanja" },
  ];
  if (type === "nvme") {
    return [
      ...common,
      { key: "percentage_used", label: "Istrošenost" },
      { key: "available_spare", label: "Rezerva" },
      { key: "media_errors", label: "Media greške" },
      { key: "data_units_written", label: "Upisano" },
      { key: "unsafe_shutdowns", label: "Nebezbedna gašenja" },
    ];
  }
  return [
    ...common,
    { key: "reallocated_sectors", label: "Realocirani" },
    { key: "pending_sectors", label: "Pending" },
    { key: "uncorrectable_sectors", label: "Neispravljivi" },
    { key: "crc_errors", label: "CRC greške" },
    { key: "total_lbas_written", label: "Upisano (LBA)" },
    { key: "ssd_life_left", label: "Vek SSD-a" },
  ];
}

/** NVMe data units su po 512 000 bajtova; za grafikon se pretvaraju u bajtove. */
function normalize(data: SeriesResponse): { unit: string; data: SeriesResponse } {
  if (data.metric !== "data_units_written") return { unit: data.unit, data };
  const scale = (v: number | null) => (v == null ? null : v * 512_000);
  return {
    unit: "B",
    data: { ...data, series: data.series.map((s) => ({ ...s, points: s.points.map((p) => ({ ...p, value: scale(p.value), min: scale(p.min), max: scale(p.max) })) })) },
  };
}

export function DiskCharts({ diskId, diskType }: { diskId: number; diskType: DiskType }) {
  const metrics = metricsFor(diskType);
  const [metric, setMetric] = useState(metrics[0].key);
  const [period, setPeriod] = useState<PeriodValue>(() => periodFromPreset("7d"));
  const query = `/metrics/disks?ids=${diskId}&metric=${metric}&${periodQuery(period)}`;
  const series = useQuery({
    queryKey: ["series", "disk", diskId, metric, period],
    queryFn: () => api<SeriesResponse>(query, { background: true }),
    placeholderData: (prev) => prev,
  });
  const alarms = useQuery({
    queryKey: ["alarms", "disk", diskId],
    queryFn: () => api<{ items: Alarm[] }>(`/alarms?status=all&disk_id=${diskId}&limit=20`, { background: true }),
  });
  const markers = (alarms.data?.items ?? [])
    .filter((a) => a.metric === metric || (metric === "temperature_c" && a.category === "temperature"))
    .map((a) => ({ ts: new Date(a.first_seen_at).getTime(), label: `alarm: ${a.title}` }));
  const normalized = series.data ? normalize(series.data) : null;
  const stats = series.data?.series[0]?.stats;
  const unit = normalized?.unit ?? "";
  const scale = series.data?.metric === "data_units_written" ? 512_000 : 1;
  const sv = (v: number | null | undefined) => (v == null ? null : v * scale);

  return (
    <Card title="Grafikoni i statistika">
      <div className="space-y-4">
        <PeriodPicker value={period} onChange={setPeriod} />
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Metrika">
          {metrics.map((m) => (
            <button
              key={m.key}
              role="tab"
              aria-selected={metric === m.key}
              onClick={() => setMetric(m.key)}
              className={`rounded-full border px-3 py-1 text-xs ${
                metric === m.key
                  ? "border-brand-700 bg-brand-50 font-medium text-brand-700 dark:border-brand-500 dark:bg-brand-700/20 dark:text-brand-500"
                  : "border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <ErrorText error={series.error} />
        {!normalized ? (
          <Spinner />
        ) : (
          <div className={series.isFetching ? "opacity-60 transition-opacity" : "transition-opacity"}>
            <TimeChart
              series={normalized.data.series}
              unit={unit}
              title={`${normalized.data.label} · interval: ${BUCKET_LABEL[normalized.data.bucket]}`}
              exportHref={(fmt) => `/api${query}&format=${fmt}`}
              markers={markers}
            />
          </div>
        )}
        {stats && stats.n > 0 && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            <div><dt className="text-slate-500">Minimum</dt><dd>{formatMetric(sv(stats.min), unit)}</dd></div>
            <div><dt className="text-slate-500">Maksimum</dt><dd>{formatMetric(sv(stats.max), unit)}</dd></div>
            <div><dt className="text-slate-500">Prosek</dt><dd>{formatMetric(sv(stats.avg), unit)}</dd></div>
            <div><dt className="text-slate-500">Očitavanja</dt><dd>{stats.n}</dd></div>
            <div><dt className="text-slate-500">Poslednja</dt><dd>{formatMetric(sv(stats.last), unit)}</dd></div>
            <div><dt className="text-slate-500">Prethodna</dt><dd>{formatMetric(sv(stats.previous), unit)}</dd></div>
            <div>
              <dt className="text-slate-500">Promena u periodu</dt>
              <dd className={stats.kind === "counter" && (stats.delta ?? 0) > 0 ? "font-semibold text-red-600 dark:text-red-400" : ""}>
                {stats.delta == null ? "—" : `${stats.delta > 0 ? "+" : ""}${formatMetric(sv(stats.delta), unit)}`}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">Brzina promene</dt>
              <dd>{stats.rate_per_day == null ? "—" : `${formatMetric(sv(stats.rate_per_day), unit)} / dan`}</dd>
            </div>
          </dl>
        )}
      </div>
    </Card>
  );
}

const WINDOWS = [
  { key: "24h", label: "24 sata", hours: 24 },
  { key: "7d", label: "7 dana", hours: 168 },
  { key: "30d", label: "30 dana", hours: 720 },
] as const;

export function DiskTrendsCard({ diskId }: { diskId: number }) {
  const trends = useQuery({
    queryKey: ["trends", diskId],
    queryFn: () => api<DiskTrends>(`/disks/${diskId}/trends`, { background: true }),
    refetchInterval: 120_000,
  });
  const entries = Object.entries(trends.data ?? {});
  return (
    <Card title="Trendovi (promena vrednosti)">
      {trends.isLoading ? (
        <Spinner />
      ) : entries.length === 0 ? (
        <EmptyState>Još nema dovoljno očitavanja za trendove.</EmptyState>
      ) : (
        <>
          <Table head={["Vrednost", "Trenutno", ...WINDOWS.map((w) => w.label)]}>
            {entries.map(([key, t]) => {
              const unit = key === "data_units_written" ? "B" : t.unit;
              const scale = key === "data_units_written" ? 512_000 : 1;
              return (
                <tr key={key}>
                  <Td>{t.label}</Td>
                  <Td>{formatMetric(t["30d"].last == null ? null : t["30d"].last * scale, unit)}</Td>
                  {WINDOWS.map((w) => {
                    const win = t[w.key];
                    const partial = win.covered_hours != null && win.covered_hours < w.hours * 0.9;
                    const bad = t.kind === "counter" && (win.delta ?? 0) > 0;
                    return (
                      <Td key={w.key} className={bad ? "font-semibold text-red-600 dark:text-red-400" : ""}>
                        {win.delta == null ? "—" : `${win.delta > 0 ? "+" : ""}${formatMetric(win.delta * scale, unit)}`}
                        {partial && win.first_at && (
                          <span className="block text-[11px] font-normal text-slate-500" title={`Prvo očitavanje u prozoru: ${formatDateTime(win.first_at)}`}>
                            podaci od {formatDateTime(win.first_at).slice(0, 10)}
                          </span>
                        )}
                      </Td>
                    );
                  })}
                </tr>
              );
            })}
          </Table>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Promena = poslednja minus prva vrednost u prozoru. Rast brojača grešaka (realocirani, pending, neispravljivi sektori, media greške) istaknut je crveno.
            Ako prozor nije pokriven podacima u celini, navodi se od kada postoje podaci.
          </p>
        </>
      )}
    </Card>
  );
}
