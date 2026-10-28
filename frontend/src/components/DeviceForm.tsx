import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { Device, Platform } from "../types";
import IntervalInput from "./IntervalInput";
import { Alert, Button, ErrorText, Field, Input, Modal, Select, Textarea } from "./ui";

const PLATFORM_OPTIONS: { value: Platform; label: string }[] = [
  { value: "truenas_scale", label: "TrueNAS SCALE" },
  { value: "truenas_core", label: "TrueNAS CORE" },
  { value: "proxmox", label: "Proxmox VE" },
  { value: "synology", label: "Synology DSM" },
];

type Props = { device?: Device; onClose: () => void; onSaved: (device: Device) => void };

export default function DeviceForm({ device, onClose, onSaved }: Props) {
  const collection = useQuery({
    queryKey: ["settings", "collection"],
    queryFn: () => api<{ default_interval_minutes: number }>("/settings/collection"),
  });
  const [form, setForm] = useState({
    name: device?.name ?? "",
    platform: device?.platform ?? ("truenas_scale" as Platform),
    host: device?.host ?? "",
    ssh_port: device?.ssh_port ?? 22,
    ssh_username: device?.ssh_username ?? "diskmonitor",
    timezone: device?.timezone ?? "Europe/Belgrade",
    use_global: device ? device.collection_interval_minutes == null : true,
    interval: device?.collection_interval_minutes ?? 15,
    connect_timeout: device?.connect_timeout ?? 15,
    command_timeout: device?.command_timeout ?? 60,
    tags: device?.tags.join(", ") ?? "",
    location: device?.location ?? "",
    note: device?.note ?? "",
  });
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }));

  const addressChanged = device && (form.host.trim() !== device.host || Number(form.ssh_port) !== device.ssh_port);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const body = {
      name: form.name,
      platform: form.platform,
      host: form.host,
      ssh_port: Number(form.ssh_port),
      ssh_username: form.ssh_username,
      timezone: form.timezone,
      collection_interval_minutes: form.use_global ? null : form.interval,
      connect_timeout: Number(form.connect_timeout),
      command_timeout: Number(form.command_timeout),
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      location: form.location || null,
      note: form.note || null,
    };
    try {
      const saved = device
        ? await api<Device>(`/devices/${device.id}`, { method: "PUT", body })
        : await api<Device>("/devices", { method: "POST", body });
      onSaved(saved);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  const timezones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["Europe/Belgrade", "UTC"];

  return (
    <Modal title={device ? `Izmena uređaja – ${device.name}` : "Novi uređaj"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Naziv">
            <Input value={form.name} onChange={(e) => set("name", e.target.value)} required maxLength={100} />
          </Field>
          <Field label="Platforma">
            <Select value={form.platform} onChange={(e) => set("platform", e.target.value as Platform)}>
              {PLATFORM_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="IP adresa ili DNS ime">
            <Input value={form.host} onChange={(e) => set("host", e.target.value)} required />
          </Field>
          <div className="grid grid-cols-[6rem_1fr] gap-3">
            <Field label="SSH port">
              <Input type="number" min={1} max={65535} value={form.ssh_port} onChange={(e) => set("ssh_port", Number(e.target.value))} required />
            </Field>
            <Field label="SSH korisnik" hint="Namenski nalog samo za nadzor, ne root.">
              <Input value={form.ssh_username} onChange={(e) => set("ssh_username", e.target.value)} required />
            </Field>
          </div>
        </div>
        {addressChanged && (
          <Alert tone="warning">Promena adrese ili porta poništava potvrđeni host ključ i isključuje nadzor dok se ključ ponovo ne potvrdi.</Alert>
        )}

        <fieldset className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <legend className="px-1 text-sm font-medium">Interval prikupljanja</legend>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.use_global} onChange={(e) => set("use_global", e.target.checked)} />
            Koristi globalni interval
            {collection.data && <span className="text-slate-500">({collection.data.default_interval_minutes} min)</span>}
          </label>
          {!form.use_global && <IntervalInput value={form.interval} onChange={(m) => set("interval", m)} />}
        </fieldset>

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Timeout konekcije (s)">
            <Input type="number" min={3} max={120} value={form.connect_timeout} onChange={(e) => set("connect_timeout", Number(e.target.value))} />
          </Field>
          <Field label="Timeout komandi (s)">
            <Input type="number" min={5} max={900} value={form.command_timeout} onChange={(e) => set("command_timeout", Number(e.target.value))} />
          </Field>
          <Field label="Vremenska zona">
            <Select value={form.timezone} onChange={(e) => set("timezone", e.target.value)}>
              {timezones.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Lokacija">
            <Input value={form.location} onChange={(e) => set("location", e.target.value)} maxLength={255} />
          </Field>
          <Field label="Oznake" hint="Odvojene zarezom">
            <Input value={form.tags} onChange={(e) => set("tags", e.target.value)} />
          </Field>
        </div>
        <Field label="Napomena">
          <Textarea rows={2} className="font-sans" value={form.note} onChange={(e) => set("note", e.target.value)} maxLength={4000} />
        </Field>

        <ErrorText error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Otkaži
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            Sačuvaj
          </Button>
        </div>
      </form>
    </Modal>
  );
}
