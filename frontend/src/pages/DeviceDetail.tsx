import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, KeyRound, Pencil, PlugZap, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import DeviceForm from "../components/DeviceForm";
import { DeviceAvailability } from "../components/Availability";
import { DeviceStorage, PrivilegeProfileCard } from "../components/DeviceStorage";
import RunsTable from "../components/RunsTable";
import { Alert, Badge, Button, Card, CopyButton, ErrorText, Field, Input, Modal, Spinner, Table, Td, Textarea } from "../components/ui";
import { DEVICE_STATUS, formatDateTime, formatInterval, formatRelative } from "../format";
import type { DeviceDetail, HostKeyInfo, Run } from "../types";

const CAPABILITY_LABELS: Record<string, string> = {
  smartctl: "SMART podaci (smartmontools)",
  lsblk: "Inventar blok uređaja",
  nvme: "NVMe alati (nvme-cli)",
  zpool: "ZFS pool status",
  zfs: "ZFS dataset-i",
  mdadm: "Linux softverski RAID",
  lvs: "LVM / LVM-thin",
  vgs: "LVM volume grupe",
  pvesm: "Proxmox storage",
  midclt: "TrueNAS middleware klijent",
  synodisk: "Synology alat za diskove",
};

function Step({ n, title, done, children }: { n: number; title: string; done: boolean; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <div
        className={`flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
          done ? "bg-emerald-600 text-white" : "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200"
        }`}
        aria-label={done ? "Završeno" : "Nije završeno"}
      >
        {done ? "✓" : n}
      </div>
      <div className="min-w-0 flex-1 space-y-2 pb-4">
        <h3 className="font-medium">{title}</h3>
        {children}
      </div>
    </div>
  );
}

export default function DeviceDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const admin = user?.role === "admin";
  const canCollect = admin || user?.role === "operator";

  const query = useQuery({
    queryKey: ["device", id],
    queryFn: () => api<DeviceDetail>(`/devices/${id}`, { background: true }),
    refetchInterval: 10_000,
  });

  const [editing, setEditing] = useState(false);
  const [keyMode, setKeyMode] = useState<"none" | "upload">("none");
  const [privateKey, setPrivateKey] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [hostKey, setHostKey] = useState<HostKeyInfo | null>(null);
  const [testResult, setTestResult] = useState<Run | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ["device", id] }),
    queryClient.invalidateQueries({ queryKey: ["devices"] }),
  ]);

  const action = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  if (query.isLoading) return <Spinner />;
  if (query.error) return <ErrorText error={query.error} />;
  const d = query.data!;
  const status = DEVICE_STATUS[d.status];
  const hostKeyConfirmed = !!d.host_key_confirmed_at;
  const ready = d.has_credentials && hostKeyConfirmed;

  return (
    <div className="space-y-4">
      <Link to="/uredjaji" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:underline">
        <ArrowLeft className="size-4" /> Uređaji
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{d.name}</h1>
          <p className="text-sm text-slate-500">
            {d.platform_label} · <span className="mono">{d.ssh_username}@{d.host}:{d.ssh_port}</span>
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge tone={d.running ? "info" : status.tone}>{d.running ? "Prikupljanje u toku" : status.label}</Badge>
            {d.tags.map((t) => (
              <Badge key={t} tone="unknown">{t}</Badge>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {canCollect && ready && (
            <>
              <Button
                icon={<PlugZap className="size-4" />}
                loading={busy === "test"}
                onClick={() =>
                  action("test", async () => {
                    const r = await api<{ run: Run }>(`/devices/${d.id}/test-connection`, { method: "POST" });
                    setTestResult(r.run);
                  })
                }
              >
                Test konekcije
              </Button>
              <Button
                icon={<RefreshCw className="size-4" />}
                disabled={d.running || !d.enabled}
                title={!d.enabled ? "Nadzor je isključen" : undefined}
                loading={busy === "collect"}
                onClick={() => action("collect", () => api(`/devices/${d.id}/collect`, { method: "POST" }))}
              >
                Prikupi sada
              </Button>
            </>
          )}
          {admin && (
            <>
              <Button icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>
                Izmeni
              </Button>
              <Button variant="danger" icon={<Trash2 className="size-4" />} onClick={() => setConfirmDelete(true)}>
                Obriši
              </Button>
            </>
          )}
        </div>
      </div>

      <ErrorText error={error} />
      {testResult && (
        <Alert tone={testResult.status === "success" ? "ok" : "critical"} title={testResult.status === "success" ? "Konekcija uspešna" : "Konekcija nije uspela"}>
          {testResult.status === "success" ? testResult.details?.os_info : testResult.error_message}
          {(testResult.details?.warnings ?? []).map((w) => (
            <p key={w} className="text-xs">⚠ {w}</p>
          ))}
        </Alert>
      )}

      {admin && (
        <Card title="Podešavanje pristupa">
          <Step n={1} title="SSH ključ za nalog na uređaju" done={d.has_credentials}>
            {d.public_key && (
              <div className="space-y-1">
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  Javni ključ dodajte u <code>~/.ssh/authorized_keys</code> naloga <code>{d.ssh_username}</code> na uređaju:
                </p>
                <div className="flex items-start gap-2">
                  <code className="block flex-1 break-all rounded bg-slate-100 p-2 text-xs dark:bg-slate-800">{d.public_key}</code>
                  <CopyButton text={d.public_key} />
                </div>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                icon={<KeyRound className="size-3.5" />}
                loading={busy === "genkey"}
                onClick={() => {
                  if (d.has_credentials && !confirm("Novi ključ zamenjuje postojeći. Stari javni ključ treba ukloniti sa uređaja. Nastaviti?")) return;
                  action("genkey", () => api(`/devices/${d.id}/generate-key`, { method: "POST" }));
                }}
              >
                {d.has_credentials ? "Generiši novi ključ" : "Generiši ključ"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setKeyMode(keyMode === "upload" ? "none" : "upload")}>
                Unesi postojeći privatni ključ
              </Button>
            </div>
            {keyMode === "upload" && (
              <div className="space-y-2">
                <Field label="Privatni ključ (OpenSSH/PEM)" hint="Ključ se čuva šifrovan i nikad se ne prikazuje ponovo.">
                  <Textarea rows={6} value={privateKey} onChange={(e) => setPrivateKey(e.target.value)} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" />
                </Field>
                <Field label="Passphrase (ako ključ ima)">
                  <Input type="password" autoComplete="off" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />
                </Field>
                <Button
                  size="sm"
                  variant="primary"
                  loading={busy === "upload"}
                  disabled={!privateKey.trim()}
                  onClick={() =>
                    action("upload", async () => {
                      await api(`/devices/${d.id}/credentials`, { method: "POST", body: { private_key: privateKey, passphrase: passphrase || null } });
                      setPrivateKey("");
                      setPassphrase("");
                      setKeyMode("none");
                    })
                  }
                >
                  Sačuvaj ključ
                </Button>
              </div>
            )}
          </Step>

          <Step n={2} title="Potvrda host ključa uređaja" done={hostKeyConfirmed}>
            {hostKeyConfirmed && (
              <p className="text-sm">
                Potvrđen otisak: <code className="break-all">{d.host_key_fingerprint}</code>
                <span className="block text-xs text-slate-500">
                  {d.host_key_confirmed_by}, {formatDateTime(d.host_key_confirmed_at)}
                </span>
              </p>
            )}
            {hostKey ? (
              <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-700 dark:bg-amber-950/30">
                <p>
                  Uređaj je predstavio ključ <b>{hostKey.key_type}</b> sa otiskom:
                </p>
                <code className="block break-all text-base">{hostKey.fingerprint}</code>
                <p>
                  Pre potvrde proverite otisak direktno na uređaju (konzola ili već pouzdana SSH sesija):
                  <code className="mt-1 block rounded bg-white p-1.5 dark:bg-slate-900">{hostKey.verify_command}</code>
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<ShieldCheck className="size-3.5" />}
                    loading={busy === "confirm"}
                    onClick={() =>
                      action("confirm", async () => {
                        await api(`/devices/${d.id}/host-key/confirm`, { method: "POST", body: { fingerprint: hostKey.fingerprint } });
                        setHostKey(null);
                      })
                    }
                  >
                    Otisak se poklapa – potvrđujem
                  </Button>
                  <Button size="sm" onClick={() => setHostKey(null)}>
                    Odustani
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                size="sm"
                loading={busy === "fetch"}
                onClick={() =>
                  action("fetch", async () => {
                    setHostKey(await api<HostKeyInfo>(`/devices/${d.id}/host-key/fetch`, { method: "POST" }));
                  })
                }
              >
                {hostKeyConfirmed ? "Ponovo preuzmi i proveri ključ" : "Preuzmi otisak host ključa"}
              </Button>
            )}
          </Step>

          <Step n={3} title="Uključivanje nadzora" done={d.enabled}>
            {!ready ? (
              <p className="text-sm text-slate-500">Dostupno nakon koraka 1 i 2. Preporuka: prvo pokrenite „Test konekcije”.</p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  size="sm"
                  variant={d.enabled ? "secondary" : "primary"}
                  loading={busy === "enable"}
                  onClick={() => action("enable", () => api(`/devices/${d.id}`, { method: "PUT", body: { enabled: !d.enabled } }))}
                >
                  {d.enabled ? "Isključi nadzor" : "Uključi nadzor"}
                </Button>
                {d.enabled && <span className="text-sm text-slate-500">Sledeće prikupljanje: {formatDateTime(d.next_run_at)}</span>}
              </div>
            )}
          </Step>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Stanje">
          <dl className="grid grid-cols-[11rem_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-slate-500">Sistem</dt>
            <dd>{d.os_info ?? "Još nije utvrđen"}</dd>
            <dt className="text-slate-500">Interval</dt>
            <dd>
              {formatInterval(d.effective_interval_minutes)}
              {d.collection_interval_minutes == null && <span className="text-slate-500"> (globalni)</span>}
            </dd>
            <dt className="text-slate-500">Sledeće prikupljanje</dt>
            <dd>{d.enabled ? formatDateTime(d.next_run_at) : "Nadzor isključen"}</dd>
            <dt className="text-slate-500">Poslednji uspešan kontakt</dt>
            <dd>
              {formatDateTime(d.last_success_at)} {d.last_success_at && <span className="text-slate-500">({formatRelative(d.last_success_at)})</span>}
            </dd>
            <dt className="text-slate-500">Poslednja greška</dt>
            <dd>
              {d.last_failure_at ? (
                <>
                  {formatDateTime(d.last_failure_at)}
                  {d.last_error && <span className="block text-red-700 dark:text-red-400">{d.last_error}</span>}
                </>
              ) : (
                "—"
              )}
            </dd>
            <dt className="text-slate-500">Timeout</dt>
            <dd>
              konekcija {d.connect_timeout} s, komande {d.command_timeout} s
            </dd>
            <dt className="text-slate-500">Lokacija</dt>
            <dd>{d.location || "—"}</dd>
            <dt className="text-slate-500">Dodat</dt>
            <dd>{formatDateTime(d.created_at)}</dd>
          </dl>
          {d.note && <p className="mt-3 whitespace-pre-wrap rounded bg-slate-50 p-2 text-sm dark:bg-slate-800">{d.note}</p>}
        </Card>

        <Card title="Dostupni alati na uređaju">
          {d.capabilities.length === 0 ? (
            <p className="text-sm text-slate-500">Biće utvrđeno pri prvom uspešnom povezivanju.</p>
          ) : (
            <Table head={["Alat", "Status", "Detalji"]}>
              {d.capabilities.map((c) => (
                <tr key={c.capability}>
                  <Td>
                    <code>{c.capability}</code>
                    <span className="block text-xs text-slate-500">{CAPABILITY_LABELS[c.capability] ?? ""}</span>
                  </Td>
                  <Td>
                    <Badge tone={c.available ? "ok" : "unknown"}>{c.available ? "Dostupan" : "Nije pronađen"}</Badge>
                  </Td>
                  <Td className="mono break-all text-xs">{c.details}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>

      <DeviceStorage deviceId={d.id} />

      <DeviceAvailability deviceId={d.id} />

      <PrivilegeProfileCard platform={d.platform} username={d.ssh_username} />

      <Card title="Istorija prikupljanja (poslednjih 10)">
        <RunsTable runs={d.last_runs} />
      </Card>

      {editing && (
        <DeviceForm
          device={d}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            refresh();
          }}
        />
      )}
      {confirmDelete && (
        <Modal title="Brisanje uređaja" onClose={() => setConfirmDelete(false)}>
          <div className="space-y-3 text-sm">
            <p>
              Uređaj <b>{d.name}</b> više neće biti prikazan ni kontaktiran. Istorijski podaci ostaju sačuvani u bazi.
            </p>
            <div className="flex justify-end gap-2">
              <Button onClick={() => setConfirmDelete(false)}>Otkaži</Button>
              <Button
                variant="danger"
                loading={busy === "delete"}
                onClick={async () => {
                  setBusy("delete");
                  try {
                    await api(`/devices/${d.id}`, { method: "DELETE" });
                    await queryClient.invalidateQueries({ queryKey: ["devices"] });
                    navigate("/uredjaji");
                  } catch (err) {
                    setError(err);
                    setConfirmDelete(false);
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                Obriši
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
