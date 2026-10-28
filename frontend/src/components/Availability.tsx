import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { formatDateTime } from "../format";
import type { AvailabilityResponse } from "../types";
import { PeriodPicker, periodFromPreset, periodQuery, type PeriodValue } from "./charts";
import { Badge, Card, EmptyState, Spinner, Table, Td } from "./ui";

function duration(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${(seconds / 3600).toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} h`;
  return `${(seconds / 86400).toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} d`;
}

/** Dostupnost uređaja: uspešni i neuspeli ciklusi po intervalu, procenat i periodi nedostupnosti. */
export function DeviceAvailability({ deviceId }: { deviceId: number }) {
  const [period, setPeriod] = useState<PeriodValue>(() => periodFromPreset("7d"));
  const data = useQuery({
    queryKey: ["availability", deviceId, period],
    queryFn: () => api<AvailabilityResponse>(`/metrics/availability?device_ids=${deviceId}&${periodQuery(period)}`, { background: true }),
    placeholderData: (prev) => prev,
  });
  const device = data.data?.devices[0];
  const rows = (device?.buckets ?? []).map((b) => ({ ts: new Date(b.t).getTime(), ok: b.ok, failed: b.failed }));
  const t = device?.totals;
  const daily = data.data?.bucket !== "hour";

  return (
    <Card title="Dostupnost uređaja">
      <div className="space-y-3">
        <PeriodPicker value={period} onChange={setPeriod} showBucket={false} />
        {!data.data ? (
          <Spinner />
        ) : !t || t.runs === 0 ? (
          <EmptyState>Nema ciklusa prikupljanja u periodu.</EmptyState>
        ) : (
          <div className={data.isFetching ? "space-y-3 opacity-60" : "space-y-3"}>
            <p className="text-sm">
              Dostupnost <b>{t.availability_percent?.toLocaleString("sr-Latn")}%</b> · {t.runs} ciklusa ({t.ok} uspešno, {t.failed} neuspešno) ·{" "}
              {t.outages === 0 ? "bez nedostupnosti" : `${t.outages} nedostupnosti, ukupno ${duration(t.outage_seconds)}`}
            </p>
            <div style={{ height: 160 }} role="img" aria-label="Uspešni i neuspeli ciklusi po intervalu">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} barCategoryGap={2} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis
                    dataKey="ts"
                    tickFormatter={(v) => new Intl.DateTimeFormat("sr-Latn-RS", daily ? { day: "2-digit", month: "2-digit" } : { hour: "2-digit", minute: "2-digit" }).format(new Date(v))}
                    tick={{ fontSize: 11, fill: "var(--chart-axis)" }}
                    stroke="var(--chart-axis)"
                    tickLine={false}
                    minTickGap={24}
                  />
                  <YAxis width={32} allowDecimals={false} tick={{ fontSize: 11, fill: "var(--chart-axis)" }} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={{ fill: "var(--chart-grid)" }}
                    labelFormatter={(v) => formatDateTime(new Date(v as number).toISOString())}
                    formatter={(value, name) => [value as number, name === "ok" ? "uspešno" : "neuspešno"]}
                    contentStyle={{ background: "var(--chart-surface)", borderColor: "var(--chart-grid)", fontSize: 12 }}
                  />
                  <Bar dataKey="ok" stackId="a" fill="var(--series-3)" maxBarSize={24} isAnimationActive={false} />
                  <Bar dataKey="failed" stackId="a" fill="var(--series-8)" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <ul className="flex gap-4 text-xs text-slate-600 dark:text-slate-300" aria-label="Legenda">
              <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-sm" style={{ background: "var(--series-3)" }} aria-hidden />uspešni ciklusi</li>
              <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-sm" style={{ background: "var(--series-8)" }} aria-hidden />neuspeli ciklusi</li>
            </ul>
            {device!.outages.length > 0 && (
              <Table head={["Početak", "Kraj", "Trajanje", "Neuspelih", "Razlog"]}>
                {[...device!.outages].reverse().map((o) => (
                  <tr key={o.start}>
                    <Td className="whitespace-nowrap">{formatDateTime(o.start)}</Td>
                    <Td className="whitespace-nowrap">{o.end ? formatDateTime(o.end) : <Badge tone="critical">i dalje traje</Badge>}</Td>
                    <Td>{duration(o.duration_seconds)}</Td>
                    <Td>{o.failed_runs}</Td>
                    <Td className="max-w-md text-xs">{o.reason ?? "—"}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
