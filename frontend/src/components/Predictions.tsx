import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatBytes } from "../format";
import { formatMetric } from "./charts";
import { Alert, Badge, Card, EmptyState, Spinner, Table, Td } from "./ui";

type Prediction = {
  disk_id: number;
  disk_label: string;
  metric: string;
  label: string;
  unit: string;
  last: number | null;
  slope_per_day: number;
  slope_per_30d: number;
  limit: number | null;
  days_to_limit: number | null;
  quality: "low" | "medium" | "good";
  quality_note: string;
};
type PoolPrediction = {
  pool_id: number;
  pool_label: string;
  slope_bytes_per_day: number;
  used_bytes: number | null;
  capacity_bytes: number | null;
  days_to_full: number | null;
  quality: "low" | "medium" | "good";
  quality_note: string;
};
type Response = { days: number; disks: Prediction[]; pools: PoolPrediction[]; note: string };

const QUALITY = {
  low: { label: "Nepouzdano", tone: "unknown" },
  medium: { label: "Okvirno", tone: "warning" },
  good: { label: "Dobri podaci", tone: "ok" },
} as const;

function eta(days: number | null): string {
  if (days == null) return "—";
  if (days > 3650) return "više od 10 godina";
  if (days > 365) return `~${(days / 365).toLocaleString("sr-Latn", { maximumFractionDigits: 1 })} god.`;
  return `~${Math.round(days)} dana`;
}

/** Procene trenda (spec. §16.1) – uvek označene kao procene, sa kvalitetom podataka. */
export default function PredictionsCard({ diskId }: { diskId?: number }) {
  const q = useQuery({ queryKey: ["predictions"], queryFn: () => api<Response>("/predictions?days=90", { background: true }), refetchInterval: 600_000 });
  if (q.isLoading) return <Spinner />;
  if (!q.data) return null;
  const disks = q.data.disks.filter((d) => (diskId ? d.disk_id === diskId : true) && (d.limit != null || Math.abs(d.slope_per_30d) >= 1 || d.metric === "temperature_c"));
  const pools = diskId ? [] : q.data.pools;
  return (
    <Card title="Prognoze (procena, ne dijagnoza)">
      <div className="space-y-3">
        <Alert tone="info">{q.data.note}</Alert>
        {disks.length === 0 && pools.length === 0 && <EmptyState>Nema vrednosti sa trendom za procenu.</EmptyState>}
        {disks.length > 0 && (
          <Table head={[...(diskId ? [] : ["Disk"]), "Vrednost", "Sada", "Trend / 30 dana", "Granica", "Procena dostizanja", "Kvalitet"]}>
            {disks.map((d) => (
              <tr key={`${d.disk_id}-${d.metric}`}>
                {!diskId && <Td><Link to={`/diskovi/${d.disk_id}`} className="hover:underline">{d.disk_label}</Link></Td>}
                <Td>{d.label}</Td>
                <Td>{formatMetric(d.last, d.unit)}</Td>
                <Td className="whitespace-nowrap">{d.slope_per_30d > 0 ? "+" : ""}{formatMetric(d.slope_per_30d, d.unit)}</Td>
                <Td>{d.limit != null ? formatMetric(d.limit, d.unit) : "—"}</Td>
                <Td>{eta(d.days_to_limit)}</Td>
                <Td><span title={d.quality_note}><Badge tone={QUALITY[d.quality].tone}>{QUALITY[d.quality].label}</Badge></span></Td>
              </tr>
            ))}
          </Table>
        )}
        {pools.length > 0 && (
          <Table head={["Pool / storage", "Zauzeto", "Rast po danu", "Puno za", "Kvalitet"]}>
            {pools.map((p) => (
              <tr key={p.pool_id}>
                <Td><Link to={`/skladiste/${p.pool_id}`} className="hover:underline">{p.pool_label}</Link></Td>
                <Td className="whitespace-nowrap">{formatBytes(p.used_bytes)} / {formatBytes(p.capacity_bytes)}</Td>
                <Td className="whitespace-nowrap">{p.slope_bytes_per_day >= 0 ? "+" : "−"}{formatBytes(Math.abs(p.slope_bytes_per_day))}</Td>
                <Td>{p.slope_bytes_per_day > 0 ? eta(p.days_to_full) : "ne raste"}</Td>
                <Td><span title={p.quality_note}><Badge tone={QUALITY[p.quality].tone}>{QUALITY[p.quality].label}</Badge></span></Td>
              </tr>
            ))}
          </Table>
        )}
        <p className="text-xs text-slate-500">Linearni trend iz poslednjih {q.data.days} dana. Pređite mišem preko kvaliteta za broj očitavanja i raspon.</p>
      </div>
    </Card>
  );
}
