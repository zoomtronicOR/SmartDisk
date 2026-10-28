import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Check, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, Card, EmptyState, ErrorText, Select, Spinner, Table, Td } from "../components/ui";
import { ALARM_STATUS, SEVERITY, formatDateTime, formatRelative } from "../format";
import type { Alarm, AlarmSummary, Severity } from "../types";

const SEVERITY_ORDER: Severity[] = ["critical", "high", "warning", "info"];

export function AlarmTarget({ a }: { a: Alarm }) {
  return (
    <span className="text-xs text-slate-500">
      {a.device_id ? <Link to={`/uredjaji/${a.device_id}`} className="hover:underline">{a.device_name}</Link> : "—"}
      {a.disk_id && (
        <> · <Link to={`/diskovi/${a.disk_id}`} className="hover:underline">{a.disk_name}</Link></>
      )}
      {a.pool_id && (
        <> · <Link to={`/skladiste/${a.pool_id}`} className="hover:underline">{a.pool_name}</Link></>
      )}
    </span>
  );
}

export default function AlarmsPage() {
  const { user } = useAuth();
  const canAct = user?.role === "admin" || user?.role === "operator";
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const summary = useQuery({ queryKey: ["alarm-summary"], queryFn: () => api<AlarmSummary>("/alarms/summary", { background: true }), refetchInterval: 15_000 });
  const list = useQuery({
    queryKey: ["alarms", status, severity],
    queryFn: () => api<{ items: Alarm[]; total: number }>(`/alarms?status=${status}${severity ? `&severity=${severity}` : ""}`, { background: true }),
    refetchInterval: 15_000,
  });

  const act = async (id: number, action: "acknowledge" | "resolve") => {
    setBusy(id);
    setError(null);
    try {
      await api(`/alarms/${id}/${action}`, { method: "POST", body: {} });
      await queryClient.invalidateQueries({ queryKey: ["alarms"] });
      await queryClient.invalidateQueries({ queryKey: ["alarm-summary"] });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Alarmi</h1>
      {summary.data && (
        <div className="flex flex-wrap gap-2">
          {SEVERITY_ORDER.map((s) => (
            <button
              key={s}
              onClick={() => { setSeverity(severity === s ? "" : s); setStatus("active"); }}
              className={`rounded-xl border px-4 py-2 text-left ${severity === s ? "border-brand-600 ring-2 ring-brand-500/30" : "border-slate-200 dark:border-slate-700"} bg-white dark:bg-slate-900`}
              aria-pressed={severity === s}
            >
              <Badge tone={SEVERITY[s].tone}>{SEVERITY[s].label}</Badge>
              <span className="ml-2 text-lg font-semibold">{summary.data.active[s]}</span>
              {summary.data.unacknowledged[s] > 0 && <span className="ml-1 text-xs text-slate-500">({summary.data.unacknowledged[s]} nepotvrđeno)</span>}
            </button>
          ))}
        </div>
      )}
      <Card>
        <div className="mb-3 flex flex-wrap gap-2">
          <Select className="max-w-56" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="active">Aktivni (otvoreni i potvrđeni)</option>
            <option value="open">Samo otvoreni</option>
            <option value="acknowledged">Samo potvrđeni</option>
            <option value="resolved">Rešeni</option>
            <option value="all">Svi</option>
          </Select>
          <Select className="max-w-48" value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Nivo">
            <option value="">Svi nivoi</option>
            {SEVERITY_ORDER.map((s) => (
              <option key={s} value={s}>{SEVERITY[s].label}</option>
            ))}
          </Select>
        </div>
        <ErrorText error={error} />
        {list.isLoading ? (
          <Spinner />
        ) : list.error ? (
          <ErrorText error={list.error} />
        ) : list.data!.items.length === 0 ? (
          <EmptyState>{status === "active" ? "Nema aktivnih alarma." : "Nema alarma za izabrane filtere."}</EmptyState>
        ) : (
          <Table head={["Nivo", "Alarm", "Status", "Prvi put", "Poslednji put", "Ponavljanja", ""]}>
            {list.data!.items.map((a) => (
              <tr key={a.id}>
                <Td><Badge tone={SEVERITY[a.severity].tone}>{SEVERITY[a.severity].label}</Badge></Td>
                <Td className="min-w-72">
                  <Link to={`/alarmi/${a.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-500">{a.title}</Link>
                  <span className="block"><AlarmTarget a={a} /></span>
                </Td>
                <Td>
                  <Badge tone={ALARM_STATUS[a.status].tone}>{ALARM_STATUS[a.status].label}</Badge>
                  {a.acknowledged_by && a.status === "acknowledged" && <span className="block text-xs text-slate-500">{a.acknowledged_by}</span>}
                </Td>
                <Td className="whitespace-nowrap">{formatDateTime(a.first_seen_at)}</Td>
                <Td className="whitespace-nowrap" ><span title={formatDateTime(a.last_seen_at)}>{formatRelative(a.last_seen_at)}</span></Td>
                <Td>{a.occurrence_count}</Td>
                <Td className="whitespace-nowrap text-right">
                  {canAct && a.status === "open" && (
                    <Button size="sm" icon={<Check className="size-3.5" />} loading={busy === a.id} onClick={() => act(a.id, "acknowledge")}>Potvrdi</Button>
                  )}
                  {canAct && a.status !== "resolved" && (
                    <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} disabled={busy === a.id} onClick={() => act(a.id, "resolve")} title="Ručno zatvori (ako uslov i dalje postoji, alarm se ponovo otvara)">
                      Zatvori
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
        <p className="mt-3 flex items-start gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <BellRing className="mt-0.5 size-3.5 shrink-0" />
          Potvrda znači „video sam”, a ne „rešeno”: alarm ostaje aktivan dok uslov traje, a ako se problem pogorša, ponovo postaje otvoren.
          Alarm se sam rešava kada uslov prestane.
        </p>
      </Card>
    </div>
  );
}
