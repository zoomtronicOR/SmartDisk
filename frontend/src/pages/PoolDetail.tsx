import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { BUCKET_LABEL, PeriodPicker, TimeChart, periodFromPreset, periodQuery, type PeriodValue } from "../components/charts";
import { PoolCard } from "../components/storage";
import { Card, ErrorText, Spinner } from "../components/ui";
import type { Pool, SeriesResponse } from "../types";

const METRICS = [
  { key: "used_bytes", label: "Zauzeće" },
  { key: "free_bytes", label: "Slobodno" },
  { key: "read_errors", label: "READ greške" },
  { key: "write_errors", label: "WRITE greške" },
  { key: "checksum_errors", label: "CKSUM greške" },
  { key: "scan_progress", label: "Scrub/resilver napredak" },
];

export default function PoolDetailPage() {
  const { id } = useParams();
  const [metric, setMetric] = useState("used_bytes");
  const [period, setPeriod] = useState<PeriodValue>(() => periodFromPreset("30d"));
  const pool = useQuery({ queryKey: ["pool", id], queryFn: () => api<Pool>(`/pools/${id}`, { background: true }), refetchInterval: 30_000 });
  const query = `/metrics/pools?ids=${id}&metric=${metric}&${periodQuery(period)}`;
  const series = useQuery({
    queryKey: ["series", "pool", id, metric, period],
    queryFn: () => api<SeriesResponse>(query, { background: true }),
    placeholderData: (prev) => prev,
  });

  if (pool.isLoading) return <Spinner />;
  if (pool.error) return <ErrorText error={pool.error} />;
  const p = pool.data!;
  const metrics = METRICS.filter((m) => p.technology === "zfs" || !m.key.endsWith("_errors"));

  return (
    <div className="space-y-4">
      <Link to="/skladiste" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:underline">
        <ArrowLeft className="size-4" /> Skladište
      </Link>
      <h1 className="text-2xl font-semibold">
        {p.name} <span className="text-base font-normal text-slate-500">· <Link to={`/uredjaji/${p.device_id}`} className="hover:underline">{p.device_name}</Link></span>
      </h1>
      <PoolCard pool={p} link={false} />
      <Card title="Istorija">
        <div className="space-y-3">
          <PeriodPicker value={period} onChange={setPeriod} />
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Metrika">
            {metrics.map((m) => (
              <button
                key={m.key}
                role="tab"
                aria-selected={metric === m.key}
                onClick={() => setMetric(m.key)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  metric === m.key ? "border-brand-700 bg-brand-50 font-medium text-brand-700 dark:bg-brand-700/20 dark:text-brand-500" : "border-slate-300 text-slate-600 dark:border-slate-600 dark:text-slate-300"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <ErrorText error={series.error} />
          {series.data ? (
            <div className={series.isFetching ? "opacity-60" : ""}>
              <TimeChart
                series={series.data.series}
                unit={series.data.unit}
                title={`${series.data.label} · interval: ${BUCKET_LABEL[series.data.bucket]}`}
                exportHref={(fmt) => `/api${query}&format=${fmt}`}
              />
            </div>
          ) : (
            <Spinner />
          )}
        </div>
      </Card>
    </div>
  );
}
