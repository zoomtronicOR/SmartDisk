import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, BellRing } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { SEVERITY, formatDateTime } from "../format";
import type { Device, PushSub, Severity } from "../types";
import { Alert, Button, Card, ErrorText, Field, Select } from "./ui";

function b64ToUint8(base64: string): Uint8Array {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

const supported = typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && window.isSecureContext;

/** Web Push u ovom pregledaču (spec. §13): dozvola, nivo, uređaji, privremeno utišavanje, proba. */
export default function PushCard() {
  const queryClient = useQueryClient();
  const subs = useQuery({ queryKey: ["push-subs"], queryFn: () => api<PushSub[]>("/notifications/push/subscriptions") });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices") });
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [minSeverity, setMinSeverity] = useState<Severity>("warning");
  const [deviceIds, setDeviceIds] = useState<number[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const permission = supported ? Notification.permission : "denied";

  useEffect(() => {
    if (!supported) return;
    navigator.serviceWorker.getRegistration("/").then(async (reg) => {
      const sub = await reg?.pushManager.getSubscription();
      setEndpoint(sub?.endpoint ?? null);
    });
  }, []);

  const [endpointHash, setEndpointHash] = useState<string | null>(null);
  useEffect(() => {
    if (!endpoint) return setEndpointHash(null);
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint)).then((buf) =>
      setEndpointHash([...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("")),
    );
  }, [endpoint]);
  const mine = subs.data?.find((s) => endpointHash && s.endpoint_hash === endpointHash);
  useEffect(() => {
    if (mine) {
      setMinSeverity(mine.min_severity);
      setDeviceIds(mine.device_ids ?? []);
    }
  }, [mine?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (key: string, fn: () => Promise<string>) => {
    setBusy(key);
    setError(null);
    setMessage(null);
    try {
      setMessage(await fn());
      await queryClient.invalidateQueries({ queryKey: ["push-subs"] });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const subscribe = (muteHours?: number) =>
    run("sub", async () => {
      if (Notification.permission !== "granted" && (await Notification.requestPermission()) !== "granted") {
        throw new Error("Pregledač nije dozvolio obaveštenja. Dozvolu možete promeniti u podešavanjima sajta (ikona katanca u adresnoj traci).");
      }
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      const { public_key } = await api<{ public_key: string }>("/notifications/push/vapid");
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(public_key) });
      }
      const json = sub.toJSON();
      await api("/notifications/push/subscriptions", {
        method: "POST",
        body: {
          endpoint: sub.endpoint, p256dh: json.keys?.p256dh, auth: json.keys?.auth, min_severity: minSeverity,
          device_ids: deviceIds.length ? deviceIds : null,
          muted_until: muteHours ? new Date(Date.now() + muteHours * 3600_000).toISOString() : null,
        },
      });
      setEndpoint(sub.endpoint);
      return muteHours ? `Obaveštenja su utišana ${muteHours} h.` : "Obaveštenja u ovom pregledaču su uključena.";
    });

  const unsubscribe = () =>
    run("unsub", async () => {
      const reg = await navigator.serviceWorker.getRegistration("/");
      const sub = await reg?.pushManager.getSubscription();
      await sub?.unsubscribe();
      if (mine) await api(`/notifications/push/subscriptions/${mine.id}`, { method: "DELETE" });
      setEndpoint(null);
      return "Obaveštenja u ovom pregledaču su isključena.";
    });

  if (!supported) {
    return (
      <Card title="Obaveštenja u pregledaču (Web Push)">
        <Alert tone="unknown">Ovaj pregledač ili veza ne podržavaju Web Push. Potreban je HTTPS sa pouzdanim sertifikatom (lokalni CA mora biti instaliran).</Alert>
      </Card>
    );
  }
  const muted = mine?.muted_until && new Date(mine.muted_until) > new Date();

  return (
    <Card title="Obaveštenja u ovom pregledaču (Web Push)">
      <div className="max-w-2xl space-y-3 text-sm">
        <p>
          Stanje:{" "}
          {mine ? (muted ? <b>utišano do {formatDateTime(mine.muted_until)}</b> : <b>uključeno</b>) : <b>isključeno</b>}
          {permission === "denied" && " · pregledač je blokirao obaveštenja za ovaj sajt"}
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Najniži nivo">
            <Select value={minSeverity} onChange={(e) => setMinSeverity(e.target.value as Severity)}>
              {(["info", "warning", "high", "critical"] as Severity[]).map((s) => <option key={s} value={s}>{SEVERITY[s].label} i više</option>)}
            </Select>
          </Field>
          <Field label="Uređaji" hint="Bez izbora = svi uređaji.">
            <div className="flex flex-wrap gap-3 pt-1">
              {(devices.data ?? []).map((d) => (
                <label key={d.id} className="flex items-center gap-1.5">
                  <input type="checkbox" checked={deviceIds.includes(d.id)} onChange={(e) => setDeviceIds(e.target.checked ? [...deviceIds, d.id] : deviceIds.filter((x) => x !== d.id))} />
                  {d.name}
                </label>
              ))}
            </div>
          </Field>
        </div>
        {message && <Alert tone="ok">{message}</Alert>}
        <ErrorText error={error} />
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" icon={<BellRing className="size-4" />} loading={busy === "sub"} onClick={() => subscribe()}>
            {mine ? "Sačuvaj izbor" : "Uključi obaveštenja"}
          </Button>
          {mine && (
            <>
              <Button loading={busy === "test"} onClick={() => run("test", async () => (await api<{ message: string }>(`/notifications/push/subscriptions/${mine.id}/test`, { method: "POST" })).message)}>
                Pošalji probu
              </Button>
              <Button onClick={() => subscribe(muted ? undefined : 8)}>{muted ? "Ukini utišavanje" : "Utišaj 8 h"}</Button>
              <Button variant="ghost" icon={<BellOff className="size-4" />} loading={busy === "unsub"} onClick={unsubscribe}>Isključi</Button>
            </>
          )}
        </div>
        {mine?.last_error && <p className="text-xs text-red-600">Poslednja greška: {mine.last_error}</p>}
        <p className="text-xs text-slate-500">Obaveštenja stižu i kada aplikacija nije otvorena, dok je pregledač pokrenut. Klik na obaveštenje otvara alarm.</p>
      </div>
    </Card>
  );
}
