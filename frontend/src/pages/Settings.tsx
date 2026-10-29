import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";
import IntervalInput from "../components/IntervalInput";
import AdvancedSettingsSection from "../components/AdvancedSettings";
import BrandingCard from "../components/BrandingCard";
import DeleteAllDevicesCard from "../components/DeleteAllDevicesCard";
import NotificationSettingsSection from "../components/NotificationSettings";
import { Alert, Badge, Button, Card, ErrorText, Field, Input, Select, Spinner } from "../components/ui";
import { formatBytes, formatDateTime } from "../format";
import type { SystemStatus } from "../types";

type CollectionSettings = { default_interval_minutes: number; raw_retention_days: number; min_minutes: number; max_minutes: number };

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const collection = useQuery({ queryKey: ["settings", "collection"], queryFn: () => api<CollectionSettings>("/settings/collection") });
  const general = useQuery({ queryKey: ["settings", "general"], queryFn: () => api<{ timezone: string }>("/settings/general") });
  const system = useQuery({ queryKey: ["system"], queryFn: () => api<SystemStatus>("/system/status", { background: true }), refetchInterval: 10_000 });

  const [interval, setInterval] = useState(15);
  const [retention, setRetention] = useState(365);
  const [timezone, setTimezone] = useState("Europe/Belgrade");
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    if (collection.data) {
      setInterval(collection.data.default_interval_minutes);
      setRetention(collection.data.raw_retention_days);
    }
  }, [collection.data]);
  useEffect(() => {
    if (general.data) setTimezone(general.data.timezone);
  }, [general.data]);

  const save = async (key: string, path: string, body: unknown) => {
    setSaving(key);
    setError(null);
    setSaved(null);
    try {
      await api(path, { method: "PUT", body });
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      await queryClient.invalidateQueries({ queryKey: ["devices"] });
      setSaved(key);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(null);
    }
  };

  if (collection.isLoading || general.isLoading) return <Spinner />;
  const timezones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [timezone];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Podešavanja</h1>
      <ErrorText error={error} />

      <Card title="Prikupljanje podataka">
        <div className="max-w-lg space-y-3">
          <Field label="Globalni podrazumevani interval" hint="Važi za sve uređaje koji nemaju sopstveni interval. Promena se primenjuje odmah, bez restarta - sledeći ciklus je „sada + novi interval”. Dozvoljeno: 1 minut - 7 dana.">
            <IntervalInput value={interval} onChange={setInterval} />
          </Field>
          {interval < 5 && <Alert tone="warning">Interval kraći od 5 minuta može nepotrebno opteretiti uređaje.</Alert>}
          <Field label="Čuvanje sirovih merenja (dana)" hint="Svako SMART i pool očitavanje čuva se ovoliko dana, a zatim se briše (svake noći u 03:30). Podrazumevano 365 dana. Dozvoljeno: 30-3650.">
            <Input type="number" min={30} max={3650} value={retention} onChange={(e) => setRetention(Number(e.target.value))} />
          </Field>
          {saved === "collection" && <Alert tone="ok">Podešavanja prikupljanja su sačuvana i primenjena.</Alert>}
          <Button
            variant="primary"
            loading={saving === "collection"}
            onClick={() => save("collection", "/settings/collection", { default_interval_minutes: interval, raw_retention_days: retention })}
          >
            Sačuvaj
          </Button>
        </div>
      </Card>

      <Card title="Opšte">
        <div className="max-w-lg space-y-3">
          <Field label="Vremenska zona prikaza">
            <Select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
              {timezones.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </Select>
          </Field>
          {saved === "general" && <Alert tone="ok">Sačuvano.</Alert>}
          <Button variant="primary" loading={saving === "general"} onClick={() => save("general", "/settings/general", { timezone })}>
            Sačuvaj
          </Button>
        </div>
      </Card>

      <BrandingCard />

      <NotificationSettingsSection />

      <AdvancedSettingsSection />

      <DeleteAllDevicesCard />

      {system.data && (
        <Card title="Stanje aplikacije">
          <dl className="grid grid-cols-[14rem_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-slate-500">Verzija</dt>
            <dd>{system.data.version}</dd>
            <dt className="text-slate-500">Scheduler</dt>
            <dd>{system.data.scheduler_running ? "Radi" : "NE RADI"} (poslednji signal {formatDateTime(system.data.scheduler_heartbeat_at)})</dd>
            <dt className="text-slate-500">Planiranih poslova</dt>
            <dd>{system.data.collection_jobs}</dd>
            <dt className="text-slate-500">Poslednje uspešno prikupljanje</dt>
            <dd>{formatDateTime(system.data.last_successful_collection_at)}</dd>
          </dl>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Meter
              label="Disk kontejnera"
              percent={pct(system.data.disk_total_bytes - system.data.disk_free_bytes, system.data.disk_total_bytes)}
              detail={`${formatBytes(system.data.disk_total_bytes - system.data.disk_free_bytes)} od ${formatBytes(system.data.disk_total_bytes)} (slobodno ${formatBytes(system.data.disk_free_bytes)})`}
            />
            <Meter
              label="Memorija"
              percent={pct(system.data.memory_used_bytes, system.data.memory_total_bytes)}
              detail={system.data.memory_total_bytes ? `${formatBytes(system.data.memory_used_bytes)} od ${formatBytes(system.data.memory_total_bytes)}` : "nije dostupno"}
            />
            <Meter
              label="Procesor"
              percent={system.data.cpu_percent}
              detail={system.data.cpu_percent != null ? `trenutno opterećenje, ${system.data.cpu_cores ?? "?"} jezgra` : "nije dostupno"}
              warning={80}
              critical={95}
            />
            <Meter
              label="Baza podataka"
              percent={pct(system.data.database_size_bytes, system.data.disk_total_bytes)}
              detail={`${formatBytes(system.data.database_size_bytes)} (udeo u disku kontejnera)`}
            />
          </div>
        </Card>
      )}
    </div>
  );
}

function pct(used: number | null | undefined, total: number | null | undefined): number | null {
  return used != null && total ? Math.round((used / total) * 1000) / 10 : null;
}

/** Zauzeće kao traka; nivo se prikazuje i bojom i oznakom sa ikonom. */
function Meter({ label, percent, detail, warning = 80, critical = 90 }: { label: string; percent: number | null; detail: string; warning?: number; critical?: number }) {
  const tone = percent == null ? "unknown" : percent >= critical ? "critical" : percent >= warning ? "warning" : "ok";
  const bar = { ok: "bg-emerald-500", warning: "bg-amber-500", critical: "bg-red-600", unknown: "bg-slate-400" }[tone];
  const text = { ok: "U redu", warning: "Visoko", critical: "Kritično", unknown: "Nema podataka" }[tone];
  return (
    <div className="space-y-1.5 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{label}</span>
        <span className="flex items-center gap-2">
          <span className="tabular-nums">{percent != null ? `${percent.toLocaleString("sr-Latn-RS")}%` : "-"}</span>
          <Badge tone={tone}>{text}</Badge>
        </span>
      </div>
      <div
        className="h-2.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
      >
        <div className={`h-full rounded-full transition-[width] duration-500 ${bar}`} style={{ width: `${Math.min(100, Math.max(percent ?? 0, percent ? 1 : 0))}%` }} />
      </div>
      <p className="text-xs text-slate-500">{detail}</p>
    </div>
  );
}
