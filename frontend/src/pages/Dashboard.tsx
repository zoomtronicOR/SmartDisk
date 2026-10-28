import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import RunsTable from "../components/RunsTable";
import { Alert, Badge, Card, ErrorText, Spinner, Stat } from "../components/ui";
import { ALARM_STATUS, DISK_STATE, SEVERITY, formatDateTime, formatRelative } from "../format";
import type { AlarmStatus, DashboardSummary } from "../types";

export default function DashboardPage() {
  const summary = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api<DashboardSummary>("/dashboard/summary", { background: true }),
    refetchInterval: 15_000,
  });

  if (summary.isLoading) return <Spinner />;
  if (summary.error) return <ErrorText error={summary.error} />;
  const data = summary.data!;
  const s = data.devices_by_status;
  const hd = data.health;
  const ds = data.disks_by_state;
  const al = data.alarms;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Pregled</h1>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Uređaji" value={data.devices_total} sub={`${s.ok} dostupno${s.error ? ` · ${s.error} sa greškom` : ""}`} tone={s.error ? "critical" : undefined} />
        <Stat
          label="Zdravlje diskova"
          value={`${hd.excellent + hd.good} / ${data.disks_total}`}
          tone={hd.critical || hd.endangered ? "critical" : hd.attention ? "warning" : undefined}
          sub={`${hd.excellent + hd.good} dobro · ${hd.attention} pažnja · ${hd.endangered} ugroženo · ${hd.critical} kritično · ${hd.unknown} nepoznato`}
        />
        <Stat
          label="Aktivni alarmi"
          value={<Link to="/alarmi" className="hover:underline">{al.critical + al.high + al.warning + al.info}</Link>}
          tone={al.critical || al.high ? "critical" : al.warning ? "warning" : undefined}
          sub={`${al.critical} kritično · ${al.high} visoko · ${al.warning} upozorenje · ${al.info} info`}
        />
        <Stat
          label="Skladište"
          value={data.pools_total}
          tone={data.pools_problem ? "critical" : undefined}
          sub={data.pools_problem ? `${data.pools_problem} sa problemom` : data.pools_scanning ? `${data.pools_scanning} - provera u toku` : "bez problema"}
        />
        <Stat
          label="Temperatura"
          value={data.max_temperature_c != null ? `${data.max_temperature_c} °C` : "-"}
          tone={data.hot_disks ? "warning" : undefined}
          sub={`najviša · ${data.hot_disks} disk(a) iznad praga za svoj tip · SMART FAILED: ${data.smart_failed_disks}`}
        />
        <Stat label="Poslednje prikupljanje" value={<span className="text-base">{formatRelative(data.last_collection_at)}</span>} sub={`sledeće: ${formatRelative(data.next_collection_at)} (${formatDateTime(data.next_collection_at)})`} />
      </div>

      {data.devices_total === 0 && (
        <Alert tone="info" title="Još nema uređaja">
          Dodajte prvi uređaj na stranici „Uređaji”.
        </Alert>
      )}
      {(s.not_configured > 0 || s.disabled > 0) && (
        <Alert tone="warning">
          {s.not_configured > 0 && `${s.not_configured} uređaj(a) nije do kraja podešeno. `}
          {s.disabled > 0 && `${s.disabled} uređaj(a) ima isključen nadzor.`}
        </Alert>
      )}

      <Card title="Zahteva pažnju">
        {data.attention.length === 0 ? (
          <p className="text-sm text-slate-600 dark:text-slate-300">
            {data.disks_total === 0
              ? "Još nema podataka o diskovima."
              : ds.unknown > 0
                ? `Nema diskova ni skladišta sa upozorenjem. Za ${ds.unknown} disk(a) nema SMART podataka - to nije isto što i „ispravno”.`
                : "Nema diskova ni skladišta sa upozorenjem."}
          </p>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.attention.map((a) => (
              <li key={`${a.kind}-${a.id}`} className="flex flex-wrap items-start gap-3 py-2 text-sm">
                <Badge tone={DISK_STATE[a.state].tone}>{a.kind === "pool" ? "Skladište" : DISK_STATE[a.state].label}</Badge>
                <div className="min-w-0 flex-1">
                  <Link to={a.kind === "disk" ? `/diskovi/${a.id}` : `/skladiste/${a.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-500">
                    {a.name}
                  </Link>
                  <span className="text-slate-500"> · {a.device_name}</span>
                  <p className="text-xs text-slate-600 dark:text-slate-400">{a.reasons.join(" ")}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {data.recent_events.length > 0 && (
        <Card title="Najnoviji događaji" actions={<Link to="/alarmi" className="text-sm text-brand-700 hover:underline dark:text-brand-500">Svi alarmi</Link>}>
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.recent_events.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-2 py-1.5 text-sm">
                <Badge tone={SEVERITY[e.severity].tone}>{SEVERITY[e.severity].label}</Badge>
                {e.status in ALARM_STATUS && <Badge tone={ALARM_STATUS[e.status as AlarmStatus].tone}>{ALARM_STATUS[e.status as AlarmStatus].label}</Badge>}
                <Link to={`/alarmi/${e.id}`} className="min-w-0 flex-1 truncate hover:underline">{e.title}</Link>
                <span className="text-xs text-slate-500" title={formatDateTime(e.last_seen_at)}>{formatRelative(e.last_seen_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Poslednja prikupljanja">
        <RunsTable runs={data.recent_runs} showDevice />
      </Card>
    </div>
  );
}
