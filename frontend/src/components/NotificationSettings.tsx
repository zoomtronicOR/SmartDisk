import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { SEVERITY, formatDateTime } from "../format";
import type { EmailSettings, MqttSettings, NotificationLogEntry, NotificationSettings, Severity, Thresholds } from "../types";
import { Alert, Badge, Button, Card, ErrorText, Field, Input, Select, Spinner, Table, Td } from "./ui";

const SEVERITIES: Severity[] = ["info", "warning", "high", "critical"];
const ENTITY_LABELS: Record<string, string> = {
  summary: "Sažetak (broj uređaja, diskova, alarma, vreme prikupljanja)",
  device_status: "Status uređaja",
  disk_temperature: "Temperatura diskova",
  disk_smart: "SMART status diskova",
  disk_health: "Zdravlje diskova",
  disk_poh: "Sati rada diskova",
  disk_wear: "NVMe istrošenost",
  pool_status: "Status pool-ova",
  pool_errors: "ZFS greške (READ/WRITE/CKSUM)",
};

function useSaver() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ key: string; text: string } | null>(null);
  const [error, setError] = useState<{ key: string; err: unknown } | null>(null);
  const run = async (key: string, fn: () => Promise<string | void>) => {
    setBusy(key);
    setMessage(null);
    setError(null);
    try {
      const text = await fn();
      setMessage({ key, text: text || "Sačuvano." });
      await queryClient.invalidateQueries({ queryKey: ["notification-settings"] });
    } catch (err) {
      setError({ key, err });
    } finally {
      setBusy(null);
    }
  };
  const feedback = (key: string) => (
    <>
      {message?.key === key && <Alert tone="ok">{message.text}</Alert>}
      {error?.key === key && <ErrorText error={error.err} />}
    </>
  );
  return { busy, run, feedback };
}

function Num({ value, onChange, min = 0, max = 10000, suffix }: { value: number; onChange: (v: number) => void; min?: number; max?: number; suffix?: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <Input type="number" className="w-20 py-1" value={value} min={min} max={max} onChange={(e) => onChange(Number(e.target.value))} />
      {suffix && <span className="text-xs text-slate-500">{suffix}</span>}
    </span>
  );
}

function Row({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="grid gap-1 py-1.5 sm:grid-cols-[18rem_1fr] sm:items-center">
      <div className="text-sm">
        {label}
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function ThresholdsCard({ initial, defaults }: { initial: Thresholds; defaults: Thresholds }) {
  const [th, setTh] = useState<Thresholds>(initial);
  useEffect(() => setTh(initial), [initial]);
  const { busy, run, feedback } = useSaver();
  const set = (path: string[], value: number) => {
    setTh((prev) => {
      const next = structuredClone(prev) as Record<string, unknown>;
      let node = next;
      for (const key of path.slice(0, -1)) node = node[key] as Record<string, unknown>;
      node[path[path.length - 1]] = value;
      return next as Thresholds;
    });
  };
  const n = (key: string) => th[key] as number;

  return (
    <Card title="Pragovi alarma">
      <div className="space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Podrazumevane vrednosti su konzervativne preporuke. Promena važi od sledećeg ciklusa prikupljanja.
        </p>
        <div>
          <h3 className="mb-1 font-medium">Temperatura (°C)</h3>
          {(["hdd", "ssd", "nvme"] as const).map((kind) => (
            <Row key={kind} label={kind.toUpperCase()} hint={`preporuka ${defaults.temperature[kind].info}/${defaults.temperature[kind].warning}/${defaults.temperature[kind].critical}`}>
              informativno <Num value={th.temperature[kind].info} onChange={(v) => set(["temperature", kind, "info"], v)} max={120} />
              upozorenje <Num value={th.temperature[kind].warning} onChange={(v) => set(["temperature", kind, "warning"], v)} max={120} />
              kritično <Num value={th.temperature[kind].critical} onChange={(v) => set(["temperature", kind, "critical"], v)} max={120} />
            </Row>
          ))}
          <Row label="Prekoračenja za nivo „visoko”" hint="broj očitavanja iznad upozorenja u 24 h">
            <Num value={n("temperature_repeat_count")} onChange={(v) => set(["temperature_repeat_count"], v)} min={1} />
          </Row>
          <Row label="Histereza" hint="alarm se zatvara tek ispod praga minus ovoliko">
            <Num value={n("temperature_hysteresis")} onChange={(v) => set(["temperature_hysteresis"], v)} max={20} suffix="°C" />
          </Row>
          <Row label="Nagli rast" hint="porast u odnosu na minimum u 24 h">
            <Num value={n("temperature_jump")} onChange={(v) => set(["temperature_jump"], v)} min={1} max={60} suffix="°C" />
          </Row>
        </div>
        <div>
          <h3 className="mb-1 font-medium">SMART brojači (dozvoljeni broj novih grešaka)</h3>
          <Row label="Realocirani sektori → „visoko”" hint="rast u 24 h / 7 dana / 30 dana">
            <Num value={n("reallocated_high_24h")} onChange={(v) => set(["reallocated_high_24h"], v)} min={1} />
            <Num value={n("reallocated_high_7d")} onChange={(v) => set(["reallocated_high_7d"], v)} min={1} />
            <Num value={n("reallocated_high_30d")} onChange={(v) => set(["reallocated_high_30d"], v)} min={1} />
          </Row>
          <Row label="Pending sektori → „visoko”" hint="rast u 24 h">
            <Num value={n("pending_high_24h")} onChange={(v) => set(["pending_high_24h"], v)} min={1} />
          </Row>
          <Row label="Neispravljivi sektori → „kritično”" hint="rast u 24 h">
            <Num value={n("uncorrectable_critical_24h")} onChange={(v) => set(["uncorrectable_critical_24h"], v)} min={1} />
          </Row>
          <Row label="CRC greške → „upozorenje”" hint="rast u 24 h (manje = informativno)">
            <Num value={n("crc_warning_24h")} onChange={(v) => set(["crc_warning_24h"], v)} min={1} />
          </Row>
        </div>
        <div>
          <h3 className="mb-1 font-medium">SSD / NVMe</h3>
          <Row label="NVMe istrošenost (%)">
            upozorenje <Num value={th.percentage_used.warning} onChange={(v) => set(["percentage_used", "warning"], v)} max={100} />
            visoko <Num value={th.percentage_used.high} onChange={(v) => set(["percentage_used", "high"], v)} max={100} />
            kritično <Num value={th.percentage_used.critical} onChange={(v) => set(["percentage_used", "critical"], v)} max={100} />
          </Row>
          <Row label="NVMe rezerva - minimum (%)" hint="koristi se veći od ovog i praga koji prijavljuje disk">
            <Num value={n("available_spare_min")} onChange={(v) => set(["available_spare_min"], v)} max={100} />
          </Row>
          <Row label="Preostali vek SSD-a (%)">
            upozorenje <Num value={th.ssd_life_left.warning} onChange={(v) => set(["ssd_life_left", "warning"], v)} max={100} />
            visoko <Num value={th.ssd_life_left.high} onChange={(v) => set(["ssd_life_left", "high"], v)} max={100} />
          </Row>
        </div>
        <div>
          <h3 className="mb-1 font-medium">Skladište, uređaji, ponašanje alarma</h3>
          <Row label="Zauzeće pool-a (%)">
            upozorenje <Num value={th.pool_usage.warning} onChange={(v) => set(["pool_usage", "warning"], v)} max={100} />
            visoko <Num value={th.pool_usage.high} onChange={(v) => set(["pool_usage", "high"], v)} max={100} />
            kritično <Num value={th.pool_usage.critical} onChange={(v) => set(["pool_usage", "critical"], v)} max={100} />
          </Row>
          <Row label="Uređaj nedostupan posle" hint="uzastopnih neuspelih ciklusa">
            <Num value={n("unreachable_runs")} onChange={(v) => set(["unreachable_runs"], v)} min={1} />
          </Row>
          <Row label="Nepotpuno prikupljanje posle" hint="uzastopnih delimičnih ciklusa">
            <Num value={n("partial_runs")} onChange={(v) => set(["partial_runs"], v)} min={1} />
          </Row>
          <Row label="Nema SMART podataka posle" hint="uzastopnih ciklusa">
            <Num value={n("no_data_runs")} onChange={(v) => set(["no_data_runs"], v)} min={1} />
          </Row>
          <Row label="Potvrda uslova" hint="1 = alarm odmah; više = tek posle toliko uzastopnih procena">
            <Num value={n("confirmations")} onChange={(v) => set(["confirmations"], v)} min={1} max={20} />
          </Row>
          <Row label="Cooldown" hint="problem koji se vrati u ovom roku ponovo otvara isti alarm, bez novog obaveštenja">
            <Num value={n("cooldown_minutes")} onChange={(v) => set(["cooldown_minutes"], v)} max={10080} suffix="min" />
          </Row>
          <Row label="Ponovno obaveštenje" hint="za nepotvrđen alarm koji traje">
            <Num value={n("renotify_hours")} onChange={(v) => set(["renotify_hours"], v)} min={1} max={720} suffix="h" />
          </Row>
        </div>
        {feedback("th")}
        <div className="flex gap-2">
          <Button variant="primary" loading={busy === "th"} onClick={() => run("th", async () => { await api("/notifications/thresholds", { method: "PUT", body: th }); return "Pragovi su sačuvani."; })}>
            Sačuvaj pragove
          </Button>
          <Button onClick={() => setTh(defaults)}>Vrati preporučene</Button>
        </div>
      </div>
    </Card>
  );
}

function EmailCard({ initial }: { initial: EmailSettings }) {
  const [f, setF] = useState({ ...initial, password: "", recipientsText: initial.recipients.join(", ") });
  useEffect(() => setF({ ...initial, password: "", recipientsText: initial.recipients.join(", ") }), [initial]);
  const { busy, run, feedback } = useSaver();
  const body = () => ({
    enabled: f.enabled, host: f.host.trim(), port: f.port, security: f.security, username: f.username.trim(),
    password: f.password ? f.password : null, from_addr: f.from_addr.trim(),
    recipients: f.recipientsText.split(/[,;\s]+/).filter(Boolean), min_severity: f.min_severity,
  });
  return (
    <Card title="E-pošta (SMTP)">
      <div className="max-w-2xl space-y-3">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Šalji obaveštenja e-poštom</label>
        <div className="grid gap-3 sm:grid-cols-[1fr_8rem_10rem]">
          <Field label="SMTP server"><Input value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} placeholder="smtp.gmail.com" /></Field>
          <Field label="Port"><Input type="number" value={f.port} onChange={(e) => setF({ ...f, port: Number(e.target.value) })} /></Field>
          <Field label="Bezbednost">
            <Select value={f.security} onChange={(e) => {
              const security = e.target.value as EmailSettings["security"];
              setF({ ...f, security, port: security === "ssl" ? 465 : security === "starttls" ? 587 : f.port });
            }}>
              <option value="starttls">STARTTLS (587)</option>
              <option value="ssl">SSL/TLS (465)</option>
              <option value="none">Bez šifrovanja</option>
            </Select>
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Korisničko ime"><Input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" /></Field>
          <Field label="Lozinka" hint={initial.has_password ? "Lozinka je sačuvana (šifrovana). Ostavite prazno da ostane ista." : "Za Gmail koristiti „App password”."}>
            <Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Pošiljalac (From)"><Input value={f.from_addr} onChange={(e) => setF({ ...f, from_addr: e.target.value })} placeholder="smartdisk@domen.rs" /></Field>
          <Field label="Najniži nivo za e-poštu">
            <Select value={f.min_severity} onChange={(e) => setF({ ...f, min_severity: e.target.value as Severity })}>
              {SEVERITIES.map((s) => <option key={s} value={s}>{SEVERITY[s].label} i više</option>)}
            </Select>
          </Field>
        </div>
        <Field label="Primaoci" hint="Više adresa razdvojiti zarezom."><Input value={f.recipientsText} onChange={(e) => setF({ ...f, recipientsText: e.target.value })} /></Field>
        {feedback("email")}
        {feedback("email-test")}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" loading={busy === "email"} onClick={() => run("email", async () => { await api("/notifications/email", { method: "PUT", body: body() }); return "SMTP podešavanja su sačuvana."; })}>Sačuvaj</Button>
          <Button icon={<Send className="size-4" />} loading={busy === "email-test"} onClick={() => run("email-test", async () => (await api<{ message: string }>("/notifications/email/test", { method: "POST", body: body() })).message)}>
            Pošalji probnu poruku
          </Button>
        </div>
      </div>
    </Card>
  );
}

function MqttCard({ initial, allEntities }: { initial: MqttSettings; allEntities: string[] }) {
  const [f, setF] = useState({ ...initial, password: "" });
  useEffect(() => setF({ ...initial, password: "" }), [initial]);
  const { busy, run, feedback } = useSaver();
  const st = initial.status;
  const body = () => {
    const { status: _s, has_password: _h, ...rest } = f;
    return { ...rest, host: f.host.trim(), password: f.password ? f.password : null };
  };
  return (
    <Card
      title="MQTT i Home Assistant"
      actions={initial.enabled ? (st.connected ? <Badge tone="ok">Povezano</Badge> : <Badge tone="critical">Nije povezano</Badge>) : <Badge tone="unknown">Isključeno</Badge>}
    >
      <div className="max-w-2xl space-y-3">
        {initial.enabled && st.last_error && <Alert tone="critical">{st.last_error}</Alert>}
        {initial.enabled && st.last_publish_at && <p className="text-xs text-slate-500">Poslednja objava: {formatDateTime(st.last_publish_at)}</p>}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.enabled} onChange={(e) => setF({ ...f, enabled: e.target.checked })} /> Objavljuj stanje i alarme na MQTT</label>
        <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
          <Field label="Broker (IP ili ime)" hint="Za Mosquitto add-on: adresa Home Assistant-a."><Input value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} placeholder="192.168.88.x" /></Field>
          <Field label="Port"><Input type="number" value={f.port} onChange={(e) => setF({ ...f, port: Number(e.target.value) })} /></Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Korisničko ime"><Input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" /></Field>
          <Field label="Lozinka" hint={initial.has_password ? "Sačuvana (šifrovana). Prazno = ostaje ista." : "U HA: poseban korisnik za SmartDisk."}>
            <Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" />
          </Field>
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.tls} onChange={(e) => setF({ ...f, tls: e.target.checked, port: e.target.checked && f.port === 1883 ? 8883 : !e.target.checked && f.port === 8883 ? 1883 : f.port })} /> TLS</label>
          {f.tls && <label className="flex items-center gap-2"><input type="checkbox" checked={f.tls_insecure} onChange={(e) => setF({ ...f, tls_insecure: e.target.checked })} /> Ne proveravaj sertifikat brokera</label>}
          <label className="flex items-center gap-2"><input type="checkbox" checked={f.retain} onChange={(e) => setF({ ...f, retain: e.target.checked })} /> Retain za stanje</label>
        </div>
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="Client ID"><Input value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })} /></Field>
          <Field label="Prefiks tema"><Input value={f.prefix} onChange={(e) => setF({ ...f, prefix: e.target.value })} /></Field>
          <Field label="QoS">
            <Select value={f.qos} onChange={(e) => setF({ ...f, qos: Number(e.target.value) })}>
              <option value={0}>0</option><option value={1}>1</option><option value={2}>2</option>
            </Select>
          </Field>
          <Field label="Heartbeat (s)"><Input type="number" value={f.heartbeat_seconds} onChange={(e) => setF({ ...f, heartbeat_seconds: Number(e.target.value) })} /></Field>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.discovery} onChange={(e) => setF({ ...f, discovery: e.target.checked })} /> Home Assistant MQTT Discovery (automatski entiteti)</label>
        {f.discovery && (
          <>
            <Field label="Discovery prefiks"><Input className="max-w-xs" value={f.discovery_prefix} onChange={(e) => setF({ ...f, discovery_prefix: e.target.value })} /></Field>
            <fieldset className="grid gap-1 text-sm sm:grid-cols-2">
              <legend className="mb-1 text-sm font-medium">Entiteti</legend>
              {allEntities.map((e) => (
                <label key={e} className="flex items-center gap-2">
                  <input type="checkbox" checked={f.entities.includes(e)} onChange={(ev) => setF({ ...f, entities: ev.target.checked ? [...f.entities, e] : f.entities.filter((x) => x !== e) })} />
                  {ENTITY_LABELS[e] ?? e}
                </label>
              ))}
            </fieldset>
          </>
        )}
        <p className="text-xs text-slate-500">
          Teme: <code>{f.prefix}/availability</code>, <code>{f.prefix}/summary</code>, <code>{f.prefix}/devices/&lt;id&gt;/state</code>, <code>{f.prefix}/disks/&lt;id&gt;/state</code>,{" "}
          <code>{f.prefix}/pools/&lt;id&gt;/state</code>, <code>{f.prefix}/events</code>. Samo telemetrija - komande se ne primaju; serijski brojevi se ne objavljuju.
        </p>
        {feedback("mqtt")}
        {feedback("mqtt-test")}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" loading={busy === "mqtt"} onClick={() => run("mqtt", async () => { await api("/notifications/mqtt", { method: "PUT", body: body() }); return "MQTT podešavanja su sačuvana; veza se ponovo uspostavlja."; })}>Sačuvaj</Button>
          <Button loading={busy === "mqtt-test"} onClick={() => run("mqtt-test", async () => (await api<{ message: string }>("/notifications/mqtt/test", { method: "POST", body: body() })).message)}>Testiraj vezu</Button>
        </div>
      </div>
    </Card>
  );
}

function GeneralCard({ initial }: { initial: { base_url: string; notify_resolved: boolean } }) {
  const [f, setF] = useState({ ...initial, base_url: initial.base_url || window.location.origin });
  useEffect(() => setF({ ...initial, base_url: initial.base_url || window.location.origin }), [initial]);
  const { busy, run, feedback } = useSaver();
  return (
    <Card title="Opšte za obaveštenja">
      <div className="max-w-2xl space-y-3">
        <Field label="Adresa aplikacije" hint="Koristi se za linkove u e-pošti i Web Push obaveštenjima."><Input value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value.trim().replace(/\/$/, "") })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.notify_resolved} onChange={(e) => setF({ ...f, notify_resolved: e.target.checked })} /> Obavesti i kada se alarm reši</label>
        {feedback("general")}
        <Button variant="primary" loading={busy === "general"} onClick={() => run("general", async () => { await api("/notifications/general", { method: "PUT", body: f }); })}>Sačuvaj</Button>
      </div>
    </Card>
  );
}

function LogCard() {
  const log = useQuery({ queryKey: ["notification-log"], queryFn: () => api<NotificationLogEntry[]>("/notifications/log?limit=50", { background: true }), refetchInterval: 30_000 });
  const channel: Record<string, string> = { push: "Web Push", email: "E-pošta", mqtt: "MQTT" };
  return (
    <Card title="Evidencija obaveštenja (poslednjih 50)">
      {!log.data ? <Spinner /> : log.data.length === 0 ? <p className="text-sm text-slate-500">Još nema poslatih obaveštenja.</p> : (
        <Table head={["Vreme", "Kanal", "Alarm", "Primalac", "Rezultat"]}>
          {log.data.map((n) => (
            <tr key={n.id}>
              <Td className="whitespace-nowrap">{formatDateTime(n.sent_at)}</Td>
              <Td>{channel[n.channel] ?? n.channel}</Td>
              <Td>{n.event_id ? <a className="text-brand-700 hover:underline dark:text-brand-500" href={`/alarmi/${n.event_id}`}>#{n.event_id}</a> : "proba"}</Td>
              <Td className="max-w-xs truncate text-xs">{n.target}</Td>
              <Td>{n.status === "sent" ? <Badge tone="ok">Poslato</Badge> : <Badge tone="critical">Neuspešno</Badge>} <span className="text-xs text-red-600">{n.error_message !== "probna poruka" ? n.error_message : ""}</span></Td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

export default function NotificationSettingsSection() {
  const settings = useQuery({ queryKey: ["notification-settings"], queryFn: () => api<NotificationSettings>("/notifications/settings") });
  if (settings.isLoading) return <Spinner />;
  if (settings.error) return <ErrorText error={settings.error} />;
  const s = settings.data!;
  return (
    <>
      <ThresholdsCard initial={s.thresholds} defaults={s.threshold_defaults} />
      <EmailCard initial={s.email} />
      <MqttCard initial={s.mqtt} allEntities={s.mqtt_entities} />
      <GeneralCard initial={s.general} />
      <LogCard />
    </>
  );
}
