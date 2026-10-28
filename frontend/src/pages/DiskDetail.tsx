import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileJson } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { DiskCharts, DiskTrendsCard } from "../components/DiskAnalytics";
import { DiskHealthCard, HealthBadge } from "../components/Health";
import { SerialNumber, Temperature } from "../components/storage";
import { Alert, Badge, Button, Card, EmptyState, ErrorText, Modal, Spinner, Table, Td } from "../components/ui";
import {
  DISK_STATE,
  DISK_TYPE,
  SMART_HEALTH,
  formatCapacity,
  formatDataUnits,
  formatDateTime,
  formatHours,
  formatNumber,
  formatRelative,
} from "../format";
import type { DiskDetail, DiskSample } from "../types";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  );
}

/** Brojač koji je > 0 ističe se crveno; NULL je „nije dostupno”, nikad 0. */
function Counter({ value, warnAbove = 0 }: { value: number | null | undefined; warnAbove?: number }) {
  if (value == null) return <span className="text-slate-400">nije dostupno</span>;
  return <span className={value > warnAbove ? "font-semibold text-red-600 dark:text-red-400" : ""}>{value.toLocaleString("sr-Latn")}</span>;
}

export default function DiskDetailPage() {
  const { id } = useParams();
  const [raw, setRaw] = useState<unknown>(null);
  const disk = useQuery({
    queryKey: ["disk", id],
    queryFn: () => api<DiskDetail>(`/disks/${id}`, { background: true }),
    refetchInterval: 30_000,
  });
  const samples = useQuery({
    queryKey: ["disk", id, "samples"],
    queryFn: () => api<DiskSample[]>(`/disks/${id}/samples?limit=50`, { background: true }),
    refetchInterval: 60_000,
  });

  if (disk.isLoading) return <Spinner />;
  if (disk.error) return <ErrorText error={disk.error} />;
  const d = disk.data!;
  // Za disk u standby-ju prikazuju se vrednosti iz poslednjeg SMART očitavanja.
  const standby = d.latest?.smart_health === "standby";
  const s = standby && d.last_smart ? d.last_smart : d.latest;
  const state = DISK_STATE[d.state];
  const smart = s ? SMART_HEALTH[s.smart_health] : null;
  const nvme = d.disk_type === "nvme";

  return (
    <div className="space-y-4">
      <Link to="/diskovi" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:underline">
        <ArrowLeft className="size-4" /> Diskovi
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{d.model ?? "Nepoznat model"}</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            <Link to={`/uredjaji/${d.device_id}`} className="hover:underline">{d.device_name}</Link> · <span className="mono">{d.device_path}</span>
            {d.pools.length > 0 && <> · pool: {d.pools.join(", ")}</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <HealthBadge level={d.health.level} score={d.health.score} />
          {smart && <Badge tone={smart.tone}>SMART: {smart.label}</Badge>}
          <Button size="sm" icon={<FileJson className="size-4" />} onClick={async () => setRaw((await api<{ raw: unknown }>(`/disks/${id}/raw`)).raw)}>
            Izvorni podaci
          </Button>
        </div>
      </div>

      {!d.is_present && <Alert tone="warning" title="Disk nije pronađen u poslednjem ciklusu">Poslednji put viđen {formatDateTime(d.last_seen_at)}. Istorija je sačuvana.</Alert>}
      {d.reasons.length > 0 && d.is_present && (
        <Alert tone={state.tone} title={d.state === "unknown" ? "Podaci nisu dostupni" : "Razlozi"}>
          <ul className="list-disc pl-4">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </Alert>
      )}
      {standby && (
        <Alert tone="info" title="Disk je u standby režimu">
          Aplikacija ga ne budi radi očitavanja.{" "}
          {d.last_smart ? `Prikazane su vrednosti iz poslednjeg SMART očitavanja (${formatDateTime(d.last_smart.collected_at)}).` : "SMART još nije očitan."}
        </Alert>
      )}
      {s?.self_test_running && <Alert tone="info">SMART self-test je u toku: {s.self_test_status}</Alert>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="lg:col-span-2"><DiskHealthCard disk={d} /></div>
        <Card title="Disk">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <Row label="Model">{d.model ?? "—"}</Row>
            <Row label="Porodica / proizvođač">{d.vendor ?? "—"}</Row>
            <Row label="Serijski broj"><SerialNumber serial={d.serial_number} /></Row>
            <Row label="WWN / identifikator"><span className="mono text-xs">{d.wwn ?? d.stable_identifier}</span></Row>
            <Row label="Firmware">{d.firmware ?? "—"}</Row>
            <Row label="Tip">{DISK_TYPE[d.disk_type]}{d.rotation_rate ? ` · ${d.rotation_rate} rpm` : ""}{d.form_factor ? ` · ${d.form_factor}` : ""}</Row>
            <Row label="Veza">{d.interface_type ?? "—"}</Row>
            <Row label="Kapacitet">{formatCapacity(d.capacity_bytes)}</Row>
            <Row label="Prvi put viđen">{formatDateTime(d.first_seen_at)}</Row>
            <Row label="Poslednje očitavanje">{s ? `${formatDateTime(s.collected_at)} (${formatRelative(s.collected_at)})` : "—"}</Row>
          </dl>
        </Card>

        <Card title="SMART – ključne vrednosti">
          {!s ? (
            <EmptyState>Još nema očitavanja.</EmptyState>
          ) : !s.smart_available ? (
            <Alert tone="unknown" title="SMART nije dostupan">{s.smart_message ?? "Uređaj nije vratio SMART podatke."}</Alert>
          ) : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <Row label="Overall-health">{smart && <Badge tone={smart.tone}>{smart.label}</Badge>}</Row>
              <Row label="Temperatura"><Temperature value={s.temperature_c} /></Row>
              <Row label="Sati rada">{formatHours(s.power_on_hours)}</Row>
              <Row label="Uključivanja">{formatNumber(s.power_cycles)}</Row>
              {nvme ? (
                <>
                  <Row label="Critical warning"><Counter value={s.critical_warning} /></Row>
                  <Row label="Istrošenost (percentage used)"><Counter value={s.percentage_used} warnAbove={89} />{s.percentage_used != null && "%"}</Row>
                  <Row label="Rezerva (available spare)">{formatNumber(s.available_spare, "%")} (prag {formatNumber(s.available_spare_threshold, "%")})</Row>
                  <Row label="Media / data integrity greške"><Counter value={s.media_errors} /></Row>
                  <Row label="Unosi u logu grešaka">{formatNumber(s.error_log_entries)}</Row>
                  <Row label="Nebezbedna gašenja">{formatNumber(s.unsafe_shutdowns)}</Row>
                  <Row label="Upisano / pročitano">{formatDataUnits(s.data_units_written)} / {formatDataUnits(s.data_units_read)}</Row>
                  <Row label="Vreme iznad temp. praga">{formatNumber(s.warning_temp_time, " min")} upozorenje · {formatNumber(s.critical_temp_time, " min")} kritično</Row>
                </>
              ) : (
                <>
                  <Row label="Realocirani sektori"><Counter value={s.reallocated_sectors} /></Row>
                  <Row label="Sektori na čekanju (pending)"><Counter value={s.pending_sectors} /></Row>
                  <Row label="Neispravljivi (offline uncorrectable)"><Counter value={s.uncorrectable_sectors} /></Row>
                  <Row label="Prijavljene neispravljive greške"><Counter value={s.reported_uncorrect} /></Row>
                  <Row label="UDMA CRC greške (kabl/veza)">{formatNumber(s.crc_errors)}</Row>
                  <Row label="Load/unload ciklusi">{formatNumber(s.load_cycles)}</Row>
                  <Row label="Start/stop">{formatNumber(s.start_stop_count)}</Row>
                  {s.ssd_life_left != null && <Row label="Preostali vek SSD-a">{s.ssd_life_left}%</Row>}
                  <Row label="Greške u SMART logu"><Counter value={s.error_log_count} /></Row>
                </>
              )}
            </dl>
          )}
        </Card>
      </div>

      {s?.attributes && s.attributes.length > 0 && (
        <Card title={`SMART atributi (${s.attributes.length})`}>
          <Table head={["ID", "Atribut", "Vrednost", "Najgora", "Prag", "Raw", "Tip", "Status"]}>
            {s.attributes.map((a) => {
              const failing = a.when_failed === "FAILING_NOW";
              const past = a.when_failed && !failing;
              return (
                <tr key={a.id} className={failing ? "bg-red-50 dark:bg-red-950/40" : ""}>
                  <Td>{a.id}</Td>
                  <Td className="mono text-xs">{a.name}</Td>
                  <Td>{a.value ?? "—"}</Td>
                  <Td>{a.worst ?? "—"}</Td>
                  <Td>{a.thresh ?? "—"}</Td>
                  <Td className="mono text-xs">{a.raw_string ?? a.raw ?? "—"}</Td>
                  <Td className="text-xs">{a.prefail ? "Pre-fail" : "Old-age"}</Td>
                  <Td>
                    {failing ? <Badge tone="critical">Ispod praga</Badge> : past ? <Badge tone="warning">Bio ispod praga</Badge> : <Badge tone="ok">OK</Badge>}
                  </Td>
                </tr>
              );
            })}
          </Table>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Raw vrednosti se prikazuju kako ih vraća disk; njihovo značenje zavisi od proizvođača (npr. Seagate stope grešaka nisu brojači grešaka).
          </p>
        </Card>
      )}

      <DiskTrendsCard diskId={d.id} />

      <DiskCharts diskId={d.id} diskType={d.disk_type} />

      <Card title="SMART self-testovi">
        {d.self_tests.length === 0 ? (
          <EmptyState>U logu diska nema zabeleženih self-testova. Aplikacija ne pokreće testove.</EmptyState>
        ) : (
          <Table head={["Test", "Rezultat", "Sati rada diska", "Prvi put viđen"]}>
            {d.self_tests.map((t, i) => (
              <tr key={i}>
                <Td>{t.test_type}</Td>
                <Td>
                  <Badge tone={t.passed === true ? "ok" : t.passed === false ? "critical" : "unknown"}>{t.status}</Badge>
                  {t.remaining_percent != null && t.remaining_percent > 0 && <span className="ml-1 text-xs text-slate-500">preostalo {t.remaining_percent}%</span>}
                </Td>
                <Td>{t.lifetime_hours != null ? formatHours(t.lifetime_hours) : "—"}</Td>
                <Td>{formatDateTime(t.first_seen_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Istorija očitavanja (poslednjih 50)">
        {samples.data && samples.data.length > 0 ? (
          <Table head={nvme ? ["Vreme", "SMART", "Temp.", "Istrošenost", "Media greške", "Upisano"] : ["Vreme", "SMART", "Temp.", "Realoc.", "Pending", "Uncorr.", "CRC"]}>
            {samples.data.map((x) => (
              <tr key={x.id}>
                <Td className="whitespace-nowrap">{formatDateTime(x.collected_at)}</Td>
                <Td><Badge tone={SMART_HEALTH[x.smart_health].tone}>{SMART_HEALTH[x.smart_health].label}</Badge></Td>
                <Td><Temperature value={x.temperature_c} /></Td>
                {nvme ? (
                  <>
                    <Td>{formatNumber(x.percentage_used, "%")}</Td>
                    <Td><Counter value={x.media_errors} /></Td>
                    <Td>{formatDataUnits(x.data_units_written)}</Td>
                  </>
                ) : (
                  <>
                    <Td><Counter value={x.reallocated_sectors} /></Td>
                    <Td><Counter value={x.pending_sectors} /></Td>
                    <Td><Counter value={x.uncorrectable_sectors} /></Td>
                    <Td>{formatNumber(x.crc_errors)}</Td>
                  </>
                )}
              </tr>
            ))}
          </Table>
        ) : (
          <EmptyState>Nema očitavanja.</EmptyState>
        )}
      </Card>

      {raw !== null && (
        <Modal title="Izvorni podaci (poslednji izlaz smartctl)" onClose={() => setRaw(null)} wide>
          <pre className="max-h-[70vh] overflow-auto rounded bg-slate-100 p-3 text-xs dark:bg-slate-950">{JSON.stringify(raw, null, 2)}</pre>
        </Modal>
      )}
    </div>
  );
}
