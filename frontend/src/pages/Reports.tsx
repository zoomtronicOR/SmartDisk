import { useQuery } from "@tanstack/react-query";
import { Download, FileText } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { PeriodPicker, periodFromPreset, periodQuery, type PeriodValue } from "../components/charts";
import { Card, EmptyState, ErrorText, Select, Spinner, Table, Td } from "../components/ui";
import { formatDateTime } from "../format";
import type { Device, ReportData } from "../types";

const DESCRIPTIONS: Record<string, string> = {
  devices: "Stanje svih uređaja, broj diskova i upozorenja, dostupnost u periodu.",
  disks: "Svi diskovi sa poslednjim SMART vrednostima (inventar).",
  disk_warnings: "Diskovi sa upozorenjem, kritičnim stanjem ili bez podataka, sa razlozima.",
  degradation: "Diskovi čije je zdravlje Pažnja, Ugroženo ili Kritično, sa razlozima i promenama u periodu.",
  smart_changes: "Brojači grešaka čija se vrednost promenila u periodu (realocirani, pending, CRC, NVMe…).",
  pool_errors: "ZFS pool-ovi, RAID nizovi i LVM: stanje, greške u periodu, scrub.",
  availability: "Periodi kada uređaj nije bio dostupan, sa trajanjem i razlogom.",
};

function cell(value: unknown, kind: string): string {
  if (value == null || value === "") return "-";
  if (kind === "datetime" && typeof value === "string") return formatDateTime(value);
  if (typeof value === "boolean") return value ? "da" : "ne";
  if (typeof value === "number") return value.toLocaleString("sr-Latn", { maximumFractionDigits: 2 });
  return String(value);
}

export default function ReportsPage() {
  const kinds = useQuery({ queryKey: ["report-kinds"], queryFn: () => api<Record<string, string>>("/reports") });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const [kind, setKind] = useState("devices");
  const [device, setDevice] = useState("");
  const [period, setPeriod] = useState<PeriodValue>(() => periodFromPreset("7d"));
  const params = `${periodQuery(period)}${device ? `&device_id=${device}` : ""}`;
  const report = useQuery({
    queryKey: ["report", kind, params],
    queryFn: () => api<ReportData>(`/reports/${kind}?${params}`),
    placeholderData: (prev) => prev,
  });
  const usesDevice = ["disks", "disk_warnings", "degradation", "smart_changes", "pool_errors"].includes(kind);
  const usesPeriod = !["disks", "disk_warnings"].includes(kind);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Izveštaji</h1>
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <nav className="space-y-1" aria-label="Vrsta izveštaja">
          {Object.entries(kinds.data ?? {}).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setKind(key)}
              aria-current={kind === key}
              className={`flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left text-sm ${
                kind === key ? "bg-brand-50 font-medium text-brand-700 dark:bg-brand-700/20 dark:text-brand-500" : "hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              <FileText className="mt-0.5 size-4 shrink-0" />
              <span>
                {label}
                <span className="block text-xs font-normal text-slate-500">{DESCRIPTIONS[key]}</span>
              </span>
            </button>
          ))}
        </nav>
        <Card
          className="min-w-0"
          title={report.data?.title ?? "Izveštaj"}
          actions={(["csv", "xlsx", "pdf"] as const).map((fmt) => (
            <a
              key={fmt}
              href={`/api/reports/${kind}?${params}&format=${fmt}`}
              download
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1 text-sm hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800"
            >
              <Download className="size-4" /> {fmt.toUpperCase()}
            </a>
          ))}
        >
          <div className="space-y-3">
            <div className="flex flex-wrap items-end gap-2">
              {usesPeriod && (
                <PeriodPicker value={period} onChange={setPeriod} showBucket={false} />
              )}
              {usesDevice && (
                <Select className="w-auto py-1" value={device} onChange={(e) => setDevice(e.target.value)} aria-label="Uređaj">
                  <option value="">Svi uređaji</option>
                  {(devices.data ?? []).map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </Select>
              )}
            </div>
            {report.data?.subtitle && <p className="text-sm text-slate-500">{report.data.subtitle}</p>}
            <ErrorText error={report.error} />
            {!report.data ? (
              <Spinner />
            ) : report.data.rows.length === 0 ? (
              <EmptyState>{kind === "smart_changes" ? "Nijedan brojač grešaka se nije promenio u periodu." : kind === "availability" ? "Nije bilo nedostupnosti u periodu." : "Nema podataka."}</EmptyState>
            ) : (
              <div className={report.isFetching ? "opacity-60" : ""}>
                <Table head={report.data.columns.map((c) => c.label)}>
                  {report.data.rows.map((row, i) => (
                    <tr key={i}>
                      {report.data!.columns.map((c) => (
                        <Td key={c.key} className={c.kind === "text" ? "" : "whitespace-nowrap"}>{cell(row[c.key], c.kind)}</Td>
                      ))}
                    </tr>
                  ))}
                </Table>
              </div>
            )}
            {report.data?.notes.map((n) => (
              <p key={n} className="text-xs text-slate-500 dark:text-slate-400">{n}</p>
            ))}
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Dnevni, nedeljni i mesečni pregled: period 24 sata, 7 dana ili 30 dana. CSV koristi „;” kao separator i otvara se direktno u Excel-u sa srpskim podešavanjima.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
