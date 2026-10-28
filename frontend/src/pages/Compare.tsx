import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { HealthBadge } from "../components/Health";
import { effectiveSample } from "../components/storage";
import { Alert, Card, EmptyState, Select, Table, Td } from "../components/ui";
import { DISK_TYPE, SMART_HEALTH, formatCapacity, formatDataUnits, formatHours, formatNumber } from "../format";
import type { Disk, DiskDetail, DiskSample } from "../types";

const MAX = 6;

type Row = { label: string; value: (d: DiskDetail, s: DiskSample | null) => string | React.ReactNode };

const ROWS: Row[] = [
  { label: "Uređaj", value: (d) => d.device_name },
  { label: "Putanja", value: (d) => d.device_path },
  { label: "Proizvođač / porodica", value: (d) => d.vendor ?? "-" },
  { label: "Tip", value: (d) => `${DISK_TYPE[d.disk_type]}${d.rotation_rate ? ` · ${d.rotation_rate} rpm` : ""}` },
  { label: "Kapacitet", value: (d) => formatCapacity(d.capacity_bytes) },
  { label: "Firmware", value: (d) => d.firmware ?? "-" },
  { label: "Zdravlje", value: (d) => <HealthBadge level={d.health.level} score={d.health.score} /> },
  { label: "SMART", value: (_, s) => (s ? SMART_HEALTH[s.smart_health].label : "-") },
  { label: "Temperatura", value: (_, s) => formatNumber(s?.temperature_c, " °C") },
  { label: "Sati rada", value: (_, s) => formatHours(s?.power_on_hours) },
  { label: "Uključivanja", value: (_, s) => formatNumber(s?.power_cycles) },
  { label: "Realocirani sektori", value: (_, s) => formatNumber(s?.reallocated_sectors) },
  { label: "Pending sektori", value: (_, s) => formatNumber(s?.pending_sectors) },
  { label: "Neispravljivi sektori", value: (_, s) => formatNumber(s?.uncorrectable_sectors) },
  { label: "UDMA CRC greške", value: (_, s) => formatNumber(s?.crc_errors) },
  { label: "SSD istrošenost / vek", value: (_, s) => (s?.percentage_used != null ? `${s.percentage_used}% istrošeno` : s?.ssd_life_left != null ? `${s.ssd_life_left}% preostalo` : "-") },
  { label: "NVMe rezerva", value: (_, s) => formatNumber(s?.available_spare, "%") },
  { label: "NVMe media greške", value: (_, s) => formatNumber(s?.media_errors) },
  { label: "Upisano (NVMe)", value: (_, s) => (s?.data_units_written != null ? formatDataUnits(s.data_units_written) : "-") },
  { label: "Pool", value: (d) => d.pools.join(", ") || "-" },
];

/** Poređenje diskova (spec. §10.6): vrednosti jedna pored druge. Raw SMART vrednosti različitih proizvođača nisu iste jedinice. */
export default function ComparePage() {
  const disks = useQuery({ queryKey: ["disks"], queryFn: () => api<Disk[]>("/disks", { background: true }) });
  const present = useMemo(() => (disks.data ?? []).filter((d) => d.is_present), [disks.data]);
  const [ids, setIds] = useState<number[]>([]);
  const chosen = ids.length ? ids : present.slice(0, 3).map((d) => d.id);
  const details = useQueries({
    queries: chosen.map((id) => ({ queryKey: ["disk", String(id)], queryFn: () => api<DiskDetail>(`/disks/${id}`, { background: true }) })),
  });
  const loaded = details.map((q) => q.data).filter(Boolean) as DiskDetail[];
  const vendors = new Set(loaded.map((d) => (d.vendor ?? d.model ?? "").split(" ")[0]));

  // Zajednički SMART atributi (po ID-u) - samo informativno
  const attrIds = useMemo(() => {
    const sets = loaded.map((d) => new Set((effectiveSample(d)?.attributes ?? []).map((a) => a.id)));
    if (sets.length < 2) return [];
    return [...sets[0]].filter((id) => sets.every((s) => s.has(id))).sort((a, b) => a - b);
  }, [loaded]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Poređenje diskova</h1>
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          {Array.from({ length: Math.min(MAX, Math.max(chosen.length + 1, 2)) }).map((_, i) => (
            <Select
              key={i}
              className="max-w-72"
              value={chosen[i] ?? ""}
              aria-label={`Disk ${i + 1}`}
              onChange={(e) => {
                const next = [...chosen];
                if (e.target.value) next[i] = Number(e.target.value);
                else next.splice(i, 1);
                setIds([...new Set(next.filter(Boolean))]);
              }}
            >
              <option value="">{i < chosen.length ? "- ukloni -" : "+ dodaj disk"}</option>
              {present.map((d) => (
                <option key={d.id} value={d.id}>{d.device_name} · {d.device_path} · {d.model}</option>
              ))}
            </Select>
          ))}
        </div>
      </Card>
      {vendors.size > 1 && (
        <Alert tone="info">
          Diskovi su različitih proizvođača: SMART raw vrednosti (npr. stope grešaka, temperature u atributima) nisu nužno iste jedinice. Porede se normalizovane vrednosti i trendovi.
        </Alert>
      )}
      {loaded.length === 0 ? (
        <EmptyState>Izaberite diskove.</EmptyState>
      ) : (
        <Card>
          <Table head={["", ...loaded.map((d) => <Link key={d.id} to={`/diskovi/${d.id}`} className="normal-case text-brand-700 hover:underline dark:text-brand-500">{d.model ?? d.device_path}</Link>)]}>
            {ROWS.map((r) => (
              <tr key={r.label}>
                <Td className="whitespace-nowrap text-slate-500">{r.label}</Td>
                {loaded.map((d) => <Td key={d.id}>{r.value(d, effectiveSample(d))}</Td>)}
              </tr>
            ))}
          </Table>
          {attrIds.length > 0 && (
            <>
              <h3 className="mb-1 mt-4 font-medium">Zajednički SMART atributi (normalizovana vrednost / raw)</h3>
              <Table head={["Atribut", ...loaded.map((d) => d.device_path)]}>
                {attrIds.map((id) => {
                  const name = effectiveSample(loaded[0])?.attributes?.find((a) => a.id === id)?.name;
                  return (
                    <tr key={id}>
                      <Td className="mono text-xs">{id} {name}</Td>
                      {loaded.map((d) => {
                        const a = effectiveSample(d)?.attributes?.find((x) => x.id === id);
                        return <Td key={d.id} className="mono text-xs">{a ? `${a.value ?? "-"} / ${a.raw_string ?? a.raw ?? "-"}` : "-"}</Td>;
                      })}
                    </tr>
                  );
                })}
              </Table>
            </>
          )}
          <p className="mt-3 text-xs text-slate-500">Istorijske trendove više diskova na jednom grafikonu prikazuje stranica Statistika.</p>
        </Card>
      )}
    </div>
  );
}
