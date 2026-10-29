import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorText, Modal, Select, Spinner, Table, Td } from "../components/ui";
import { formatDateTime } from "../format";
import type { AuditEntry } from "../types";

const PAGE = 50;

const ACTION_LABELS: Record<string, string> = {
  "login.success": "Uspešna prijava",
  "login.failure": "Neuspešna prijava",
  "login.locked": "Prijava na zaključan nalog",
  "login.rate_limited": "Prijava odbijena (previše pokušaja)",
  logout: "Odjava",
  "user.created": "Kreiran korisnik",
  "user.updated": "Izmenjen korisnik",
  "user.password_reset": "Reset lozinke",
  "user.password_changed": "Promena lozinke",
  "user.unlocked": "Otključan nalog",
  "user.auto_locked": "Automatsko zaključavanje",
  "user.sessions_revoked": "Odjavljene sesije",
  "device.created": "Dodat uređaj",
  "device.updated": "Izmenjen uređaj",
  "device.deleted": "Obrisan uređaj",
  "device.deleted_all": "Obrisani svi uređaji",
  "device.delete_all_denied": "Odbijeno brisanje svih uređaja",
  "device.credentials_set": "Postavljen SSH ključ",
  "device.host_key_fetched": "Preuzet host ključ",
  "device.host_key_confirmed": "Potvrđen host ključ",
  "device.host_key_changed": "Promenjen host ključ",
  "device.test_connection": "Test konekcije",
  "device.collect_manual": "Ručno prikupljanje",
  "alarm.acknowledged": "Potvrđen alarm",
  "alarm.resolved": "Ručno zatvoren alarm",
  "backup.created": "Napravljen backup",
  "token.created": "Napravljen API token",
  "token.revoked": "Opozvan API token",
  "push.subscribed": "Uključena push obaveštenja",
  "push.unsubscribed": "Isključena push obaveštenja",
  "settings.collection_updated": "Promena prikupljanja",
  "settings.general_updated": "Promena opštih podešavanja",
  "settings.thresholds_updated": "Promena pragova alarma",
  "settings.email_updated": "Promena SMTP podešavanja",
  "settings.mqtt_updated": "Promena MQTT podešavanja",
  "settings.notify_general_updated": "Promena opštih obaveštenja",
  "settings.channel_updated": "Promena kanala obaveštenja",
  "settings.maintenance": "Režim održavanja",
  "settings.report_schedule_saved": "Sačuvan zakazani izveštaj",
  "settings.report_schedule_deleted": "Obrisan zakazani izveštaj",
  "settings.backup_updated": "Promena podešavanja backup-a",
  "settings.time_updated": "Promena NTP servera",
};

type Device = {
  summary?: string;
  ip?: string | null;
  hostname?: string | null;
  browser?: string | null;
  browser_version?: string | null;
  os?: string | null;
  os_version?: string | null;
  device?: string | null;
  user_agent?: string;
  proxy?: string | null;
  client?: Record<string, unknown> | null;
};

// Polja koja šalje pregledač pri prijavi
const CLIENT_LABELS: Record<string, string> = {
  platform: "Platforma (Client Hints)",
  platform_version: "Verzija platforme",
  architecture: "Arhitektura procesora",
  bitness: "Bitnost",
  model: "Model uređaja",
  mobile: "Mobilni uređaj",
  browser_full: "Pregledač (tačna verzija)",
  screen: "Ekran",
  pixel_ratio: "Gustina piksela",
  viewport: "Prozor pregledača",
  color_depth: "Dubina boja (bit)",
  timezone: "Vremenska zona računara",
  language: "Jezik",
  languages: "Jezici",
  cores: "Procesorskih jezgara",
  memory_gb: "Memorija (GB, približno)",
  touch_points: "Dodirnih tačaka",
  color_scheme: "Tema sistema",
  cookies: "Kolačići uključeni",
  online: "Na mreži",
};

const RESULT_TONE: Record<string, "ok" | "critical" | "warning"> = { "uspešno": "ok", "neuspešno": "critical", "odbijeno": "warning" };

function value(v: unknown): string {
  if (v === null || v === undefined || v === "") return "-";
  if (typeof v === "boolean") return v ? "da" : "ne";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(10rem,auto)_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Svi detalji jednog zapisa; za prijave i podaci o računaru i pregledaču. */
function AuditDetail({ entry, onClose }: { entry: AuditEntry; onClose: () => void }) {
  const d = (entry.details ?? {}) as Record<string, unknown>;
  const device = d.device as Device | undefined;
  const result = d.result as string | undefined;
  const rest = Object.entries(d).filter(([k]) => !["device", "result", "reason", "username"].includes(k));
  return (
    <Modal title={ACTION_LABELS[entry.action] ?? entry.action} onClose={onClose} wide>
      <div className="max-h-[75vh] space-y-4 overflow-y-auto">
        <Rows
          rows={[
            ["Vreme", formatDateTime(entry.created_at)],
            ["Korisnik", entry.username ?? (d.username as string) ?? "-"],
            ["Radnja", <code key="a" className="text-xs">{entry.action}</code>],
            ...(result ? [["Rezultat", <Badge key="r" tone={RESULT_TONE[result] ?? "unknown"}>{result}</Badge>] as [string, ReactNode]] : []),
            ...(d.reason ? [["Razlog", value(d.reason)] as [string, ReactNode]] : []),
            ["Objekat", entry.entity_type ? `${entry.entity_type} #${entry.entity_id}` : "-"],
            ["IP adresa", entry.source_ip ?? "-"],
          ]}
        />
        {device && (
          <section className="space-y-2">
            <h3 className="font-medium">Računar i pregledač</h3>
            {device.summary && <p className="rounded bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">{device.summary}</p>}
            <Rows
              rows={[
                ["IP adresa", value(device.ip)],
                ["Ime računara (DNS)", device.hostname ?? "nije poznato (lokalni DNS ne zna ime)"],
                ["Pregledač", `${value(device.browser)} ${device.browser_version ?? ""}`],
                ["Operativni sistem", `${value(device.os)} ${device.os_version ?? ""}`],
                ["Vrsta uređaja", value(device.device)],
                ...(device.proxy ? [["Prosleđeno preko (X-Forwarded-For)", device.proxy] as [string, ReactNode]] : []),
                ...Object.entries(device.client ?? {}).map(([k, v]) => [CLIENT_LABELS[k] ?? k, value(v)] as [string, ReactNode]),
                ["User-Agent", <code key="ua" className="break-all text-xs">{device.user_agent || "-"}</code>],
              ]}
            />
            <p className="text-xs text-slate-500">
              MAC adresa, korisničko ime na računaru i slični podaci nisu dostupni web aplikaciji. Ime računara se dobija samo ako ga lokalni DNS (ruter) zna.
            </p>
          </section>
        )}
        {rest.length > 0 && (
          <section className="space-y-2">
            <h3 className="font-medium">Detalji</h3>
            <Rows rows={rest.map(([k, v]) => [k, <span key={k} className="mono text-xs">{value(v)}</span>])} />
          </section>
        )}
        <details className="text-xs">
          <summary className="cursor-pointer text-slate-500">Izvorni zapis (JSON)</summary>
          <pre className="mt-2 overflow-auto rounded bg-slate-100 p-2 dark:bg-slate-950">{JSON.stringify(entry, null, 2)}</pre>
        </details>
      </div>
    </Modal>
  );
}

function shortDetails(e: AuditEntry): ReactNode {
  const d = (e.details ?? {}) as Record<string, unknown>;
  const device = d.device as Device | undefined;
  if (device) {
    return (
      <span>
        {d.result ? <Badge tone={RESULT_TONE[d.result as string] ?? "unknown"}>{String(d.result)}</Badge> : null}
        {d.reason ? <span className="ml-1 text-red-700 dark:text-red-400">{String(d.reason)}</span> : null}
        <span className="block text-slate-500">{device.summary}</span>
      </span>
    );
  }
  return e.details ? <span className="mono break-all">{JSON.stringify(e.details).slice(0, 140)}</span> : "";
}

export default function AuditPage() {
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const query = useQuery({
    queryKey: ["audit", offset, action],
    queryFn: () => api<{ items: AuditEntry[]; total: number }>(`/audit?limit=${PAGE}&offset=${offset}${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Audit log</h1>
      <Card
        actions={
          <Select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOffset(0);
            }}
            className="max-w-56"
            aria-label="Vrsta radnje"
          >
            <option value="">Sve radnje</option>
            <option value="login">Prijave (uspešne i neuspešne)</option>
            <option value="login.failure">Samo neuspešne prijave</option>
            <option value="user.">Korisnici</option>
            <option value="device.">Uređaji</option>
            <option value="alarm.">Alarmi</option>
            <option value="settings.">Podešavanja</option>
            <option value="token.">API tokeni</option>
          </Select>
        }
      >
        {query.isLoading ? (
          <Spinner />
        ) : query.error ? (
          <ErrorText error={query.error} />
        ) : (
          <>
            <Table head={["Vreme", "Korisnik", "Radnja", "Objekat", "IP", "Detalji"]}>
              {query.data!.items.map((e) => (
                <tr
                  key={e.id}
                  className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/60"
                  onClick={() => setSelected(e)}
                  tabIndex={0}
                  onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && setSelected(e)}
                  aria-label={`Detalji: ${ACTION_LABELS[e.action] ?? e.action}`}
                >
                  <Td className="whitespace-nowrap">{formatDateTime(e.created_at)}</Td>
                  <Td>{e.username ?? ((e.details as Record<string, unknown> | null)?.username as string) ?? "-"}</Td>
                  <Td>
                    {ACTION_LABELS[e.action] ?? e.action}
                    <code className="block text-xs text-slate-400">{e.action}</code>
                  </Td>
                  <Td>{e.entity_type ? `${e.entity_type} #${e.entity_id}` : "-"}</Td>
                  <Td className="mono text-xs">{e.source_ip ?? "-"}</Td>
                  <Td className="max-w-md text-xs">{shortDetails(e)}</Td>
                </tr>
              ))}
            </Table>
            <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
              <span>
                {query.data!.total === 0 ? "Nema zapisa" : `${offset + 1}-${Math.min(offset + PAGE, query.data!.total)} od ${query.data!.total}`}
                {" · klik na red prikazuje sve detalje"}
              </span>
              <div className="flex gap-2">
                <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                  Prethodna
                </Button>
                <Button size="sm" disabled={offset + PAGE >= query.data!.total} onClick={() => setOffset(offset + PAGE)}>
                  Sledeća
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
      {selected && <AuditDetail entry={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
