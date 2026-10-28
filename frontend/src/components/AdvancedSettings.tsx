import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Send, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { SEVERITY, formatBytes, formatDateTime } from "../format";
import type { Severity } from "../types";
import type { TimeInfo } from "./Clock";
import { Alert, Badge, Button, Card, ErrorText, Field, Input, Select, Spinner, Table, Td } from "./ui";

const SEVERITIES: Severity[] = ["info", "warning", "high", "critical"];

function useAction() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ key: string; text: string } | null>(null);
  const [err, setErr] = useState<{ key: string; e: unknown } | null>(null);
  const run = async (key: string, fn: () => Promise<string | void>, invalidate?: string[]) => {
    setBusy(key);
    setMsg(null);
    setErr(null);
    try {
      setMsg({ key, text: (await fn()) || "Sačuvano." });
      for (const k of invalidate ?? []) await queryClient.invalidateQueries({ queryKey: [k] });
    } catch (e) {
      setErr({ key, e });
    } finally {
      setBusy(null);
    }
  };
  const feedback = (key: string) => (
    <>
      {msg?.key === key && <Alert tone="ok">{msg.text}</Alert>}
      {err?.key === key && <ErrorText error={err.e} />}
    </>
  );
  return { busy, run, feedback };
}

function TimeCard() {
  // Poseban ključ: sat u zaglavlju keširuje isti podatak u drugom obliku (sa izračunatim odstupanjem).
  const time = useQuery({ queryKey: ["system-time-settings"], queryFn: () => api<TimeInfo>("/system/time") });
  const [server, setServer] = useState("");
  useEffect(() => { if (time.data) setServer(time.data.ntp_server); }, [time.data]);
  const { busy, run, feedback } = useAction();
  const t = time.data;
  return (
    <Card title="Vreme i NTP">
      {!t ? <Spinner /> : (
        <div className="max-w-2xl space-y-3 text-sm">
          <dl className="grid grid-cols-[14rem_1fr] gap-y-1">
            <dt className="text-slate-500">Sinhronizacija sata (host)</dt>
            <dd>{t.host_synchronized === true ? <Badge tone="ok">Sinhronizovano</Badge> : t.host_synchronized === false ? <Badge tone="critical">Nije sinhronizovano</Badge> : <Badge tone="unknown">Nepoznato</Badge>}</dd>
            <dt className="text-slate-500">Odstupanje od NTP servera</dt>
            <dd>{t.offset_ms != null ? `${t.offset_ms} ms (kašnjenje mreže ${t.delay_ms} ms, stratum ${t.stratum})` : "—"}</dd>
            <dt className="text-slate-500">Poslednja provera</dt>
            <dd>{formatDateTime(t.checked_at)}</dd>
          </dl>
          {t.error && <Alert tone="warning">{t.error}</Alert>}
          <p className="text-xs text-slate-500">SmartDisk radi u LXC kontejneru, koji koristi sat Proxmox hosta. Aplikacija proverava tačnost na svakih 15 minuta; ako sat odstupa, ispravlja se NTP-om na hostu.</p>
          <Field label="NTP server za proveru" hint="Npr. pool.ntp.org, time.cloudflare.com ili adresa rutera.">
            <Input className="max-w-sm" value={server} onChange={(e) => setServer(e.target.value.trim())} />
          </Field>
          {feedback("ntp")}
          <Button variant="primary" loading={busy === "ntp"} onClick={() => run("ntp", async () => {
            const r = await api<{ offset_ms: number | null; error: string | null }>("/settings/time", { method: "PUT", body: { ntp_server: server } });
            return r.error ? `Sačuvano, ali: ${r.error}` : `Sačuvano. Odstupanje: ${r.offset_ms} ms.`;
          }, ["system-time-settings", "system-time"])}>Sačuvaj i proveri</Button>
        </div>
      )}
    </Card>
  );
}

function MaintenanceCard() {
  const settings = useQuery({ queryKey: ["notification-settings"], queryFn: () => api<{ general: { maintenance_until: string | null; maintenance_note: string } }>("/notifications/settings") });
  const [hours, setHours] = useState(4);
  const [note, setNote] = useState("");
  const { busy, run, feedback } = useAction();
  const until = settings.data?.general.maintenance_until;
  const active = until && new Date(until) > new Date();
  return (
    <Card title="Režim održavanja" actions={active ? <Badge tone="warning">Aktivan</Badge> : <Badge tone="unknown">Isključen</Badge>}>
      <div className="max-w-2xl space-y-3 text-sm">
        <p>Tokom održavanja (zamena diska, restart, scrub) šalju se samo <b>kritična</b> obaveštenja. Alarmi se i dalje beleže, a MQTT telemetrija radi.</p>
        {active && <Alert tone="warning">Održavanje traje do {formatDateTime(until)}{settings.data?.general.maintenance_note ? ` – ${settings.data.general.maintenance_note}` : ""}.</Alert>}
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Trajanje (sati)"><Input type="number" min={1} max={168} className="max-w-24" value={hours} onChange={(e) => setHours(Number(e.target.value))} /></Field>
          <Field label="Napomena"><Input className="max-w-72" value={note} onChange={(e) => setNote(e.target.value)} placeholder="npr. zamena diska u DataPool" /></Field>
        </div>
        {feedback("m")}
        <div className="flex gap-2">
          <Button variant="primary" loading={busy === "m"} onClick={() => run("m", async () => {
            await api("/notifications/maintenance", { method: "PUT", body: { until: new Date(Date.now() + hours * 3600_000).toISOString(), note } });
            return `Režim održavanja je uključen na ${hours} h.`;
          }, ["notification-settings"])}>{active ? "Produži" : "Uključi"}</Button>
          {active && <Button loading={busy === "m-off"} onClick={() => run("m", async () => { await api("/notifications/maintenance", { method: "PUT", body: { until: null, note: "" } }); return "Režim održavanja je isključen."; }, ["notification-settings"])}>Završi održavanje</Button>}
        </div>
      </div>
    </Card>
  );
}

type ChannelCfg = Record<string, { enabled: boolean; min_severity: Severity; chat_id?: string; url?: string; has_bot_token?: boolean; has_app_token?: boolean; has_user_key?: boolean; has_secret?: boolean }>;

function ChannelForm({ name, title, cfg, children, values, setValues }: {
  name: string; title: string; cfg: ChannelCfg[string]; children: ReactNode;
  values: Record<string, string>; setValues: (v: Record<string, string>) => void;
}) {
  const [enabled, setEnabled] = useState(cfg.enabled);
  const [minSev, setMinSev] = useState<Severity>(cfg.min_severity);
  const { busy, run, feedback } = useAction();
  const body = () => ({ enabled, min_severity: minSev, ...Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v === "" ? null : v])) });
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">{title}</h3>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Uključeno</label>
      </div>
      {children}
      <Field label="Najniži nivo">
        <Select className="max-w-60" value={minSev} onChange={(e) => setMinSev(e.target.value as Severity)}>
          {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY[s].label} i više</option>)}
        </Select>
      </Field>
      {feedback(name)}
      <div className="flex gap-2">
        <Button size="sm" variant="primary" loading={busy === `${name}-s`} onClick={() => run(name, async () => { await api(`/notifications/channels/${name}`, { method: "PUT", body: body() }); setValues(Object.fromEntries(Object.keys(values).map((k) => [k, k === "chat_id" || k === "url" ? values[k] : ""]))); }, ["channels"])}>Sačuvaj</Button>
        <Button size="sm" icon={<Send className="size-3.5" />} loading={busy === `${name}-t`} onClick={() => run(name, async () => (await api<{ message: string }>(`/notifications/channels/${name}/test`, { method: "POST", body: body() })).message)}>Pošalji probu</Button>
      </div>
    </div>
  );
}

function ChannelsCard() {
  const q = useQuery({ queryKey: ["channels"], queryFn: () => api<ChannelCfg>("/notifications/channels") });
  const [tg, setTg] = useState<Record<string, string>>({ chat_id: "", bot_token: "" });
  const [po, setPo] = useState<Record<string, string>>({ app_token: "", user_key: "" });
  const [wh, setWh] = useState<Record<string, string>>({ url: "", secret: "" });
  useEffect(() => {
    if (q.data) {
      setTg((v) => ({ ...v, chat_id: q.data.telegram.chat_id ?? "" }));
      setWh((v) => ({ ...v, url: q.data.webhook.url ?? "" }));
    }
  }, [q.data]);
  if (!q.data) return <Card title="Dodatni kanali"><Spinner /></Card>;
  const c = q.data;
  const saved = (has?: boolean) => (has ? "Sačuvano (šifrovano). Prazno = ostaje isto." : undefined);
  return (
    <Card title="Dodatni kanali obaveštenja">
      <div className="grid gap-3 lg:grid-cols-3">
        <ChannelForm name="telegram" title="Telegram" cfg={c.telegram} values={tg} setValues={setTg}>
          <Field label="Token bota" hint={saved(c.telegram.has_bot_token) ?? "Od @BotFather."}><Input type="password" value={tg.bot_token} onChange={(e) => setTg({ ...tg, bot_token: e.target.value })} autoComplete="off" /></Field>
          <Field label="Chat ID" hint="Vaš ID ili ID grupe (npr. od @userinfobot)."><Input value={tg.chat_id} onChange={(e) => setTg({ ...tg, chat_id: e.target.value })} /></Field>
        </ChannelForm>
        <ChannelForm name="pushover" title="Pushover" cfg={c.pushover} values={po} setValues={setPo}>
          <Field label="API token aplikacije" hint={saved(c.pushover.has_app_token)}><Input type="password" value={po.app_token} onChange={(e) => setPo({ ...po, app_token: e.target.value })} autoComplete="off" /></Field>
          <Field label="Korisnički ključ" hint={saved(c.pushover.has_user_key)}><Input type="password" value={po.user_key} onChange={(e) => setPo({ ...po, user_key: e.target.value })} autoComplete="off" /></Field>
        </ChannelForm>
        <ChannelForm name="webhook" title="Webhook (npr. Home Assistant)" cfg={c.webhook} values={wh} setValues={setWh}>
          <Field label="URL" hint="POST sa JSON telom događaja."><Input value={wh.url} onChange={(e) => setWh({ ...wh, url: e.target.value })} placeholder="http://homeassistant:8123/api/webhook/…" /></Field>
          <Field label="Tajna (HMAC, opciono)" hint={saved(c.webhook.has_secret) ?? "Potpis u zaglavlju X-SmartDisk-Signature."}><Input type="password" value={wh.secret} onChange={(e) => setWh({ ...wh, secret: e.target.value })} autoComplete="off" /></Field>
        </ChannelForm>
      </div>
    </Card>
  );
}

type Schedule = { id?: string; enabled: boolean; name: string; kinds: string[]; period: "daily" | "weekly" | "monthly"; hour: number; weekday: number; format: "pdf" | "xlsx" | "csv"; recipients: string[]; last_sent_at?: string | null; last_status?: string | null };
const WEEKDAYS = ["", "ponedeljak", "utorak", "sreda", "četvrtak", "petak", "subota", "nedelja"];
const PERIOD = { daily: "Dnevno", weekly: "Nedeljno", monthly: "Mesečno (1. u mesecu)" };

function SchedulesCard() {
  const list = useQuery({ queryKey: ["report-schedules"], queryFn: () => api<Schedule[]>("/report-schedules") });
  const kinds = useQuery({ queryKey: ["report-kinds"], queryFn: () => api<Record<string, string>>("/reports") });
  const empty: Schedule = { enabled: true, name: "Nedeljni pregled", kinds: ["devices", "disk_warnings"], period: "weekly", hour: 7, weekday: 1, format: "pdf", recipients: [] };
  const [edit, setEdit] = useState<Schedule | null>(null);
  const [rcpt, setRcpt] = useState("");
  const { busy, run, feedback } = useAction();
  return (
    <Card title="Zakazani izveštaji (e-pošta)" actions={!edit && <Button size="sm" onClick={() => { setEdit(empty); setRcpt(""); }}>Novi raspored</Button>}>
      <div className="space-y-3 text-sm">
        <p className="text-slate-500">Izveštaji se šalju kao prilog e-poštom (potrebno je podešen SMTP). Bez navedenih primalaca koriste se primaoci iz SMTP podešavanja.</p>
        {feedback("sch")}
        {(list.data ?? []).length > 0 && (
          <Table head={["Naziv", "Kada", "Izveštaji", "Format", "Poslednje slanje", ""]}>
            {list.data!.map((s) => (
              <tr key={s.id}>
                <Td>{s.name} {!s.enabled && <Badge tone="unknown">isključen</Badge>}</Td>
                <Td className="whitespace-nowrap">{PERIOD[s.period]}{s.period === "weekly" ? `, ${WEEKDAYS[s.weekday]}` : ""} u {String(s.hour).padStart(2, "0")}:05</Td>
                <Td className="text-xs">{s.kinds.map((k) => kinds.data?.[k] ?? k).join(", ")}</Td>
                <Td>{s.format.toUpperCase()}</Td>
                <Td className="text-xs">{formatDateTime(s.last_sent_at)} {s.last_status && s.last_status !== "ok" && <span className="text-red-600">{s.last_status}</span>}</Td>
                <Td className="whitespace-nowrap text-right">
                  <Button size="sm" icon={<Send className="size-3.5" />} loading={busy === `send-${s.id}`} onClick={() => run("sch", async () => (await api<{ message: string }>(`/report-schedules/${s.id}/send`, { method: "POST" })).message, ["report-schedules"])}>Pošalji sada</Button>
                  <Button size="sm" variant="ghost" onClick={() => { setEdit(s); setRcpt(s.recipients.join(", ")); }}>Izmeni</Button>
                  <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} aria-label="Obriši" onClick={() => run("sch", async () => { await api(`/report-schedules/${s.id}`, { method: "DELETE" }); return "Raspored je obrisan."; }, ["report-schedules"])} />
                </Td>
              </tr>
            ))}
          </Table>
        )}
        {edit && (
          <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <div className="grid gap-2 sm:grid-cols-4">
              <Field label="Naziv"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
              <Field label="Učestalost"><Select value={edit.period} onChange={(e) => setEdit({ ...edit, period: e.target.value as Schedule["period"] })}>{Object.entries(PERIOD).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              {edit.period === "weekly" && <Field label="Dan"><Select value={edit.weekday} onChange={(e) => setEdit({ ...edit, weekday: Number(e.target.value) })}>{WEEKDAYS.slice(1).map((d, i) => <option key={d} value={i + 1}>{d}</option>)}</Select></Field>}
              <Field label="Sat"><Input type="number" min={0} max={23} value={edit.hour} onChange={(e) => setEdit({ ...edit, hour: Number(e.target.value) })} /></Field>
              <Field label="Format"><Select value={edit.format} onChange={(e) => setEdit({ ...edit, format: e.target.value as Schedule["format"] })}><option value="pdf">PDF</option><option value="xlsx">XLSX</option><option value="csv">CSV</option></Select></Field>
            </div>
            <fieldset className="grid gap-1 sm:grid-cols-2">
              <legend className="text-sm font-medium">Izveštaji u prilogu</legend>
              {Object.entries(kinds.data ?? {}).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={edit.kinds.includes(k)} onChange={(e) => setEdit({ ...edit, kinds: e.target.checked ? [...edit.kinds, k] : edit.kinds.filter((x) => x !== k) })} /> {label}</label>
              ))}
            </fieldset>
            <Field label="Primaoci (opciono)" hint="Razdvojiti zarezom."><Input value={rcpt} onChange={(e) => setRcpt(e.target.value)} /></Field>
            <label className="flex items-center gap-2"><input type="checkbox" checked={edit.enabled} onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })} /> Uključen</label>
            <div className="flex gap-2">
              <Button variant="primary" loading={busy === "save"} onClick={() => run("sch", async () => {
                await api("/report-schedules", { method: "PUT", body: { ...edit, recipients: rcpt.split(/[,;\s]+/).filter(Boolean) } });
                setEdit(null);
                return "Raspored je sačuvan.";
              }, ["report-schedules"])}>Sačuvaj raspored</Button>
              <Button onClick={() => setEdit(null)}>Otkaži</Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

type Backups = { settings: { enabled: boolean; hour: number; keep: number; last: { file?: string; status: string; error?: string; finished_at?: string; size_bytes?: number; entries?: number } | null }; files: { file: string; size_bytes: number; created_at: string }[]; directory: string };

function BackupCard() {
  const q = useQuery({ queryKey: ["backups"], queryFn: () => api<Backups>("/backups") });
  const [f, setF] = useState({ enabled: true, hour: 2, keep: 14 });
  useEffect(() => { if (q.data) setF({ enabled: q.data.settings.enabled, hour: q.data.settings.hour, keep: q.data.settings.keep }); }, [q.data]);
  const { busy, run, feedback } = useAction();
  const last = q.data?.settings.last;
  return (
    <Card title={<span className="inline-flex items-center gap-2"><Database className="size-4" /> Backup baze</span>}>
      {!q.data ? <Spinner /> : (
        <div className="space-y-3 text-sm">
          {last ? (
            last.status === "ok"
              ? <Alert tone="ok">Poslednji backup: {formatDateTime(last.finished_at)} – {last.file} ({formatBytes(last.size_bytes)}, provera integriteta: {last.entries} stavki).</Alert>
              : <Alert tone="critical" title="Poslednji backup nije uspeo">{last.error}</Alert>
          ) : <Alert tone="warning">Backup još nije napravljen.</Alert>}
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex items-center gap-2"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Svakog dana u</label>
            <Input type="number" min={0} max={23} className="max-w-20" value={f.hour} onChange={(e) => setF({ ...f, hour: Number(e.target.value) })} />
            <span>h, čuva se poslednjih</span>
            <Input type="number" min={1} max={365} className="max-w-20" value={f.keep} onChange={(e) => setF({ ...f, keep: Number(e.target.value) })} />
            <span>backup-a</span>
          </div>
          {feedback("b")}
          <div className="flex gap-2">
            <Button variant="primary" loading={busy === "bs"} onClick={() => run("b", async () => { await api("/backups/settings", { method: "PUT", body: f }); }, ["backups"])}>Sačuvaj</Button>
            <Button loading={busy === "bn"} onClick={() => run("b", async () => { const r = await api<{ file: string }>("/backups", { method: "POST" }); return `Backup ${r.file} je napravljen i proveren.`; }, ["backups", "system"])}>Napravi backup sada</Button>
          </div>
          {q.data.files.length > 0 && (
            <Table head={["Fajl", "Napravljen", "Veličina"]}>
              {q.data.files.map((b) => <tr key={b.file}><Td className="mono text-xs">{b.file}</Td><Td>{formatDateTime(b.created_at)}</Td><Td>{formatBytes(b.size_bytes)}</Td></tr>)}
            </Table>
          )}
          <p className="text-xs text-slate-500">
            Fajlovi su u <code>{q.data.directory}</code> na kontejneru. Backup sadrži bazu i podešavanja, ali <b>ne i master ključ</b> (<code>/etc/smartdisk/smartdisk.env</code>) –
            čuvajte ga posebno, bez njega šifrovani SSH ključevi i lozinke nisu upotrebljivi. Vraćanje je opisano u dokumentaciji (instalacija.md → Backup i vraćanje).
          </p>
        </div>
      )}
    </Card>
  );
}

export default function AdvancedSettingsSection() {
  return (
    <>
      <TimeCard />
      <MaintenanceCard />
      <ChannelsCard />
      <SchedulesCard />
      <BackupCard />
    </>
  );
}
