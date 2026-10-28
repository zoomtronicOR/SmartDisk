import { useQuery } from "@tanstack/react-query";
import { ChartLine, Gauge } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import DiskGauges from "../components/Gauges";
import PredictionsCard from "../components/Predictions";
import { BUCKET_LABEL, PeriodPicker, SERIES_COLORS, TimeChart, formatMetric, periodFromPreset, periodQuery, type PeriodValue } from "../components/charts";
import { Alert, Card, EmptyState, ErrorText, Select, Spinner, Table, Td } from "../components/ui";
import { DISK_TYPE, formatBytes, formatHours, formatNumber } from "../format";
import type { Disk, MetricCatalog, SeriesResponse, StatsOverview } from "../types";

function hours(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} h`;
}

export default function StatisticsPage() {
  const [period, setPeriod] = useState<PeriodValue>(() => periodFromPreset("7d"));
  const [metric, setMetric] = useState("temperature_c");
  const [view, setView] = useState<"chart" | "gauges">(() => {
    try {
      return localStorage.getItem("sd-stats-view") === "gauges" ? "gauges" : "chart";
    } catch {
      return "chart";
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("sd-stats-view", view);
    } catch {
      /* lokalno skladište nije dostupno */
    }
  }, [view]);
  const [selected, setSelected] = useState<number[]>([]);
  // Disk zadržava svoju boju dok je izabran (boja prati disk, ne redosled); oslobođena boja ide sledećem.
  const [slots, setSlots] = useState<Record<number, number>>({});

  const catalog = useQuery({ queryKey: ["metrics-catalog"], queryFn: () => api<MetricCatalog>("/metrics/catalog") });
  const disks = useQuery({ queryKey: ["disks"], queryFn: () => api<Disk[]>("/disks", { background: true }) });
  const overview = useQuery({
    queryKey: ["stats-overview", period],
    queryFn: () => api<StatsOverview>(`/stats/overview?${periodQuery(period)}`, { background: true }),
    placeholderData: (prev) => prev,
  });

  const present = useMemo(() => (disks.data ?? []).filter((d) => d.is_present), [disks.data]);
  const ids = selected.length > 0 ? selected : present.slice(0, 4).map((d) => d.id);
  const max = catalog.data?.max_series ?? 8;
  const query = ids.length ? `/metrics/disks?ids=${ids.join(",")}&metric=${metric}&${periodQuery(period)}` : null;
  const series = useQuery({
    queryKey: ["series", "compare", ids, metric, period],
    queryFn: () => api<SeriesResponse>(query!, { background: true }),
    enabled: !!query,
    placeholderData: (prev) => prev,
  });

  const groups = useMemo(() => {
    const map = new Map<string, Disk[]>();
    for (const d of present) map.set(d.device_name, [...(map.get(d.device_name) ?? []), d]);
    return [...map.entries()];
  }, [present]);

  const slotMap = useMemo(() => {
    const map: Record<number, number> = {};
    const used = new Set<number>();
    for (const id of ids) {
      if (slots[id] != null && !used.has(slots[id])) {
        map[id] = slots[id];
        used.add(slots[id]);
      }
    }
    for (const id of ids) {
      if (map[id] == null) {
        const free = SERIES_COLORS.findIndex((_, i) => !used.has(i));
        map[id] = free;
        used.add(free);
      }
    }
    return map;
  }, [ids, slots]);

  const toggle = (id: number) => {
    const base = selected.length > 0 ? selected : ids;
    setSlots(slotMap);
    if (base.includes(id)) setSelected(base.filter((x) => x !== id));
    else if (base.length < max) setSelected([...base, id]);
  };

  const unit = series.data?.metric === "data_units_written" ? "B" : (series.data?.unit ?? "");
  const scale = series.data?.metric === "data_units_written" ? 512_000 : 1;
  const chartSeries = (series.data?.series ?? []).map((s) => ({
    ...s,
    color: SERIES_COLORS[slotMap[s.id]] ?? "var(--chart-axis)",
    points: s.points.map((p) => ({ ...p, value: p.value == null ? null : p.value * scale, min: p.min == null ? null : p.min * scale, max: p.max == null ? null : p.max * scale })),
  }));
  const colorOf = (id: number) => (slotMap[id] != null ? SERIES_COLORS[slotMap[id]] : "transparent");
  const o = overview.data;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Statistika</h1>
      <div className="flex flex-wrap items-end gap-2">
        <PeriodPicker value={period} onChange={setPeriod} showBucket={view === "chart"} />
        <div className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5 dark:border-slate-600 dark:bg-slate-900" role="group" aria-label="Način prikaza">
          {([["chart", "Grafikon", ChartLine], ["gauges", "Merači", Gauge]] as const).map(([key, label, Icon]) => (
            <button
              key={key}
              type="button"
              aria-pressed={view === key}
              onClick={() => setView(key)}
              className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-sm ${view === key ? "bg-brand-700 font-medium text-white" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}
            >
              <Icon className="size-4" aria-hidden /> {label}
            </button>
          ))}
        </div>
      </div>

      {view === "gauges" && (
        <Card title="Merači po disku">
          <div className="space-y-3">
            <Select className="max-w-80" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metrika">
              {Object.entries(catalog.data?.disk ?? {}).map(([key, m]) => (
                <option key={key} value={key}>{m.label}</option>
              ))}
            </Select>
            <DiskGauges disks={present} metric={metric} metricLabel={catalog.data?.disk[metric]?.label ?? metric} />
          </div>
        </Card>
      )}

      <PredictionsCard />

      {view === "chart" && (
      <Card title="Poređenje diskova kroz vreme">
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <div className="space-y-3">
            <Select value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metrika">
              {Object.entries(catalog.data?.disk ?? {}).map(([key, m]) => (
                <option key={key} value={key}>{m.label}</option>
              ))}
            </Select>
            <p className="text-xs text-slate-500">Diskovi (najviše {max}):</p>
            <div className="max-h-96 space-y-3 overflow-y-auto overflow-x-hidden pr-1">
              {groups.map(([device, list]) => (
                <fieldset key={device}>
                  <legend className="text-xs font-semibold text-slate-600 dark:text-slate-300">{device}</legend>
                  {list.map((d) => {
                    const checked = ids.includes(d.id);
                    return (
                      <label key={d.id} className="flex min-w-0 cursor-pointer items-center gap-2 py-0.5 text-sm">
                        <input type="checkbox" checked={checked} disabled={!checked && ids.length >= max} onChange={() => toggle(d.id)} />
                        <span className="inline-block h-0.5 w-3 shrink-0 rounded" style={{ background: checked ? colorOf(d.id) : "transparent" }} aria-hidden />
                        <span className="min-w-0 truncate" title={`${d.device_path} ${d.model ?? ""}`}>
                          <span className="mono text-xs">{d.device_path}</span> {d.model} <span className="text-xs text-slate-500">({DISK_TYPE[d.disk_type]})</span>
                        </span>
                      </label>
                    );
                  })}
                </fieldset>
              ))}
            </div>
          </div>
          <div className="min-w-0 space-y-3">
            <ErrorText error={series.error} />
            {(metric === "total_lbas_written" || metric.endsWith("_errors") || metric.endsWith("_sectors")) && ids.length > 1 && (
              <Alert tone="info">Raw vrednosti SMART atributa različitih proizvođača nisu nužno iste jedinice - poredite trend, a ne apsolutne vrednosti.</Alert>
            )}
            {!series.data ? (
              ids.length ? <Spinner /> : <EmptyState>Izaberite diskove.</EmptyState>
            ) : (
              <div className={series.isFetching ? "opacity-60" : ""}>
                <TimeChart
                  series={chartSeries}
                  unit={unit}
                  height={320}
                  title={`${series.data.label} · interval: ${BUCKET_LABEL[series.data.bucket]}`}
                  exportHref={(fmt) => `/api${query}&format=${fmt}`}
                />
              </div>
            )}
            {series.data && (
              <Table head={["Disk", "Min", "Maks", "Prosek", "Poslednja", "Promena", "Po danu"]}>
                {series.data.series.map((s) => (
                  <tr key={s.id}>
                    <Td>
                      <span className="mr-1.5 inline-block h-0.5 w-3 rounded align-middle" style={{ background: colorOf(s.id) }} aria-hidden />
                      <Link to={`/diskovi/${s.id}`} className="hover:underline">{s.label}</Link>
                    </Td>
                    <Td>{formatMetric(s.stats.min == null ? null : s.stats.min * scale, unit)}</Td>
                    <Td>{formatMetric(s.stats.max == null ? null : s.stats.max * scale, unit)}</Td>
                    <Td>{formatMetric(s.stats.avg == null ? null : s.stats.avg * scale, unit)}</Td>
                    <Td>{formatMetric(s.stats.last == null ? null : s.stats.last * scale, unit)}</Td>
                    <Td className={s.stats.kind === "counter" && (s.stats.delta ?? 0) > 0 ? "font-semibold text-red-600 dark:text-red-400" : ""}>
                      {s.stats.delta == null ? "-" : `${s.stats.delta > 0 ? "+" : ""}${formatMetric(s.stats.delta * scale, unit)}`}
                    </Td>
                    <Td>{s.stats.rate_per_day == null ? "-" : formatMetric(s.stats.rate_per_day * scale, unit)}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </div>
        </div>
      </Card>
      )}

      {overview.isLoading && <Spinner />}
      {o && (
        <div className={`grid gap-4 xl:grid-cols-2 ${overview.isFetching ? "opacity-60" : ""}`}>
          <Card title="Temperatura u periodu (min / prosek / maks)">
            {o.temperature.length === 0 ? (
              <EmptyState>Nema očitavanja temperature.</EmptyState>
            ) : (
              <Table head={["Disk", "Min", "Prosek", "Maks"]}>
                {o.temperature.map((t) => (
                  <tr key={t.id}>
                    <Td><Link to={`/diskovi/${t.id}`} className="hover:underline">{t.label}</Link></Td>
                    <Td>{t.min} °C</Td>
                    <Td>{t.avg.toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} °C</Td>
                    <Td className={t.max >= 50 ? "font-semibold text-amber-700 dark:text-amber-400" : ""}>{t.max} °C</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
          <div className="space-y-4">
            <Card title="Najviše radnih sati">
              <Table head={["Disk", "Sati rada"]}>
                {o.power_on_hours.map((r) => (
                  <tr key={r.id}>
                    <Td><Link to={`/diskovi/${r.id}`} className="hover:underline">{r.label}</Link></Td>
                    <Td className="whitespace-nowrap">{formatHours(r.value)}</Td>
                  </tr>
                ))}
              </Table>
            </Card>
            <Card title="Najveća istrošenost (SSD/NVMe)">
              {o.wear.length === 0 ? (
                <EmptyState>Nijedan disk ne prijavljuje istrošenost.</EmptyState>
              ) : (
                <Table head={["Disk", "Istrošeno", "Izvor"]}>
                  {o.wear.map((r) => (
                    <tr key={r.id}>
                      <Td><Link to={`/diskovi/${r.id}`} className="hover:underline">{r.label}</Link></Td>
                      <Td>{r.value}%</Td>
                      <Td className="text-xs text-slate-500">{r.source}</Td>
                    </tr>
                  ))}
                </Table>
              )}
            </Card>
          </div>
          <Card title="Skladište: zauzeće i trend">
            <Table head={["Pool / storage", "Zauzeto", "Promena u periodu", "Po danu", "Puno za"]}>
              {o.pools.map((p) => (
                <tr key={p.id}>
                  <Td><Link to={`/skladiste/${p.id}`} className="hover:underline">{p.label}</Link></Td>
                  <Td className="whitespace-nowrap">
                    {formatBytes(p.used_bytes)} / {formatBytes(p.capacity_bytes)}
                    {p.used_bytes != null && p.capacity_bytes ? ` (${Math.round((100 * p.used_bytes) / p.capacity_bytes)}%)` : ""}
                  </Td>
                  <Td className="whitespace-nowrap">{p.delta_bytes == null ? "-" : `${p.delta_bytes >= 0 ? "+" : "−"}${formatBytes(Math.abs(p.delta_bytes))}`}</Td>
                  <Td className="whitespace-nowrap">{p.rate_bytes_per_day == null ? "-" : `${p.rate_bytes_per_day >= 0 ? "+" : "−"}${formatBytes(Math.abs(p.rate_bytes_per_day))}`}</Td>
                  <Td className="whitespace-nowrap">{p.days_to_full == null ? "-" : `~${formatNumber(Math.round(p.days_to_full))} dana`}</Td>
                </tr>
              ))}
            </Table>
            <p className="mt-2 text-xs text-slate-500">„Puno za” je gruba procena iz linearnog rasta u izabranom periodu; za kratke periode nije pouzdana.</p>
          </Card>
          <Card title="Dostupnost uređaja">
            <Table head={["Uređaj", "Dostupnost", "Ciklusa", "Neuspelih", "Nedostupnosti", "Ukupno nedostupno", "Najduže"]}>
              {o.availability.map((a) => (
                <tr key={a.id}>
                  <Td><Link to={`/uredjaji/${a.id}`} className="hover:underline">{a.name}</Link></Td>
                  <Td className={a.availability_percent != null && a.availability_percent < 99 ? "font-semibold text-amber-700 dark:text-amber-400" : ""}>
                    {a.availability_percent == null ? "-" : `${a.availability_percent.toLocaleString("sr-Latn")}%`}
                  </Td>
                  <Td>{a.runs}</Td>
                  <Td>{a.failed}</Td>
                  <Td>{a.outages}</Td>
                  <Td>{hours(a.outage_seconds)}</Td>
                  <Td>{hours(a.longest_outage_seconds)}</Td>
                </tr>
              ))}
            </Table>
            <p className="mt-2 text-xs text-slate-500">Iz planiranih i ručnih ciklusa; testovi konekcije se ne računaju. Diskova sa SMART FAILED u periodu: {o.smart_failed_disks}.</p>
          </Card>
        </div>
      )}
    </div>
  );
}
