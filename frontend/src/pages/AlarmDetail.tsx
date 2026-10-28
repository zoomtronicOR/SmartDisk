import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, MessageSquare, X } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Alert, Badge, Button, Card, ErrorText, Spinner, Table, Td, Textarea } from "../components/ui";
import { ALARM_STATUS, HISTORY_ACTION, SEVERITY, formatDateTime } from "../format";
import type { AlarmDetail } from "../types";
import { AlarmTarget } from "./Alarms";

const CHANNEL: Record<string, string> = { push: "Web Push", email: "E-pošta", mqtt: "MQTT" };

export default function AlarmDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const canAct = user?.role === "admin" || user?.role === "operator";
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const alarm = useQuery({ queryKey: ["alarm", id], queryFn: () => api<AlarmDetail>(`/alarms/${id}`, { background: true }), refetchInterval: 20_000 });

  const act = async (action: "acknowledge" | "resolve" | "comment") => {
    setBusy(action);
    setError(null);
    try {
      await api(`/alarms/${id}/${action}`, { method: "POST", body: { comment: comment.trim() || null } });
      setComment("");
      await queryClient.invalidateQueries({ queryKey: ["alarm", id] });
      await queryClient.invalidateQueries({ queryKey: ["alarms"] });
      await queryClient.invalidateQueries({ queryKey: ["alarm-summary"] });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  if (alarm.isLoading) return <Spinner />;
  if (alarm.error) return <ErrorText error={alarm.error} />;
  const a = alarm.data!;

  return (
    <div className="space-y-4">
      <Link to="/alarmi" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:underline">
        <ArrowLeft className="size-4" /> Alarmi
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{a.title}</h1>
          <AlarmTarget a={a} />
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={SEVERITY[a.severity].tone}>{SEVERITY[a.severity].label}</Badge>
          <Badge tone={ALARM_STATUS[a.status].tone}>{ALARM_STATUS[a.status].label}</Badge>
        </div>
      </div>
      <Alert tone={SEVERITY[a.severity].tone}>{a.message}</Alert>
      {a.max_severity !== a.severity && (
        <p className="text-sm text-slate-500">Najviši dostignuti nivo: {SEVERITY[a.max_severity].label}.</p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Podaci">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-slate-500">Kategorija / pravilo</dt><dd>{a.category} · <code className="text-xs">{a.rule}</code></dd>
            {a.metric && (<><dt className="text-slate-500">Parametar</dt><dd><code className="text-xs">{a.metric}</code></dd></>)}
            {(a.previous_value != null || a.current_value != null) && (
              <><dt className="text-slate-500">Prethodna → trenutna</dt><dd>{a.previous_value ?? "—"} → {a.current_value ?? "—"}</dd></>
            )}
            {a.period && (<><dt className="text-slate-500">Period analize</dt><dd>{a.period}</dd></>)}
            <dt className="text-slate-500">Prvi put</dt><dd>{formatDateTime(a.first_seen_at)}</dd>
            <dt className="text-slate-500">Poslednji put</dt><dd>{formatDateTime(a.last_seen_at)}</dd>
            <dt className="text-slate-500">Ponavljanja</dt><dd>{a.occurrence_count}</dd>
            {a.acknowledged_at && (<><dt className="text-slate-500">Potvrdio</dt><dd>{a.acknowledged_by}, {formatDateTime(a.acknowledged_at)}</dd></>)}
            {a.resolved_at && (<><dt className="text-slate-500">Rešen</dt><dd>{formatDateTime(a.resolved_at)} · {a.resolved_by ?? "automatski (uslov više ne važi)"}</dd></>)}
            <dt className="text-slate-500">Poslednje obaveštenje</dt><dd>{formatDateTime(a.last_notified_at)}</dd>
          </dl>
        </Card>
        <Card title="Radnje">
          {canAct ? (
            <div className="space-y-3">
              <Textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Komentar (opciono za potvrdu i zatvaranje)" maxLength={2000} />
              <div className="flex flex-wrap gap-2">
                {a.status === "open" && (
                  <Button variant="primary" icon={<Check className="size-4" />} loading={busy === "acknowledge"} onClick={() => act("acknowledge")}>Potvrdi</Button>
                )}
                <Button icon={<MessageSquare className="size-4" />} loading={busy === "comment"} disabled={!comment.trim()} onClick={() => act("comment")}>Dodaj komentar</Button>
                {a.status !== "resolved" && (
                  <Button variant="ghost" icon={<X className="size-4" />} loading={busy === "resolve"} onClick={() => act("resolve")}>Zatvori ručno</Button>
                )}
              </div>
              <ErrorText error={error} />
              <p className="text-xs text-slate-500">Potvrda ne znači da je problem rešen. Ručno zatvoren alarm se ponovo otvara ako uslov i dalje postoji.</p>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Uloga „Pregled” ne može da potvrđuje alarme.</p>
          )}
        </Card>
      </div>

      <Card title="Istorija">
        <Table head={["Vreme", "Promena", "Nivo", "Korisnik", "Komentar"]}>
          {a.history.map((h, i) => (
            <tr key={i}>
              <Td className="whitespace-nowrap">{formatDateTime(h.created_at)}</Td>
              <Td>{HISTORY_ACTION[h.action] ?? h.action}</Td>
              <Td>{h.severity ? <Badge tone={SEVERITY[h.severity].tone}>{SEVERITY[h.severity].label}</Badge> : ""}</Td>
              <Td>{h.username ?? "sistem"}</Td>
              <Td className="max-w-md">{h.comment}</Td>
            </tr>
          ))}
        </Table>
      </Card>
      <Card title="Poslata obaveštenja">
        {a.notifications.length === 0 ? (
          <p className="text-sm text-slate-500">Nijedan kanal obaveštenja nije bio aktivan za ovaj alarm.</p>
        ) : (
          <Table head={["Vreme", "Kanal", "Primalac", "Rezultat"]}>
            {a.notifications.map((n, i) => (
              <tr key={i}>
                <Td className="whitespace-nowrap">{formatDateTime(n.sent_at)}</Td>
                <Td>{CHANNEL[n.channel] ?? n.channel}</Td>
                <Td className="max-w-xs truncate text-xs">{n.target}</Td>
                <Td>{n.status === "sent" ? <Badge tone="ok">Poslato</Badge> : <Badge tone="critical">Neuspešno</Badge>} <span className="text-xs text-red-600">{n.error_message}</span></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
