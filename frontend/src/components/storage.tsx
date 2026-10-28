import { ChevronDown, ChevronUp, Eye, EyeOff, Thermometer } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  DISK_TYPE,
  POOL_TECH,
  SCAN_LABEL,
  SMART_HEALTH,
  formatBytes,
  formatCapacity,
  formatDateTime,
  formatHours,
  formatNumber,
  formatRelative,
  maskSerial,
  poolTone,
} from "../format";
import type { Disk, Pool } from "../types";
import { HealthBadge } from "./Health";
import { Alert, Badge, Button, EmptyState, Table, Td } from "./ui";

/** Serijski broj je podrazumevano maskiran; prikazuje se klikom (spec. 6.2). */
export function SerialNumber({ serial }: { serial: string | null }) {
  const [shown, setShown] = useState(false);
  if (!serial) return <span>-</span>;
  return (
    <span className="inline-flex items-center gap-1">
      <span className="mono">{shown ? serial : maskSerial(serial)}</span>
      <button
        type="button"
        className="rounded p-0.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
        onClick={() => setShown(!shown)}
        aria-label={shown ? "Sakrij serijski broj" : "Prikaži serijski broj"}
        title={shown ? "Sakrij serijski broj" : "Prikaži serijski broj"}
      >
        {shown ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      </button>
    </span>
  );
}

export function Temperature({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-slate-400">-</span>;
  const cls = value >= 60 ? "text-red-600 dark:text-red-400" : value >= 50 ? "text-amber-600 dark:text-amber-400" : "";
  return (
    <span className={`inline-flex items-center gap-0.5 whitespace-nowrap ${cls}`}>
      <Thermometer className="size-3.5" aria-hidden />
      {value} °C
    </span>
  );
}

/** allocation: prostor dodeljen volumenima (LVM VG) - visok procenat je uobičajen i nije upozorenje. */
export function UsageBar({ used, total, allocation }: { used: number | null; total: number | null; allocation?: boolean }) {
  if (used == null || !total) return <span className="text-slate-400">-</span>;
  const pct = Math.min(100, (used / total) * 100);
  const color = allocation ? "bg-slate-400 dark:bg-slate-500" : pct >= 90 ? "bg-red-500" : pct >= 80 ? "bg-amber-500" : "bg-brand-600";
  return (
    <div className="min-w-32">
      <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700" role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label="Zauzeće">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
        {allocation ? "Dodeljeno volumenima: " : ""}
        {formatBytes(used)} od {formatBytes(total)} ({pct.toLocaleString("sr-Latn", { maximumFractionDigits: 1 })}%)
      </p>
    </div>
  );
}

/** Vrednosti za prikaz: za disk u standby-ju poslednje očitavanje sa SMART podacima. */
export function effectiveSample(d: Disk) {
  return d.latest?.smart_health === "standby" && d.last_smart ? d.last_smart : d.latest;
}

function errorCount(d: Disk): number | null {
  const s = effectiveSample(d);
  if (!s) return null;
  const values = [s.reallocated_sectors, s.pending_sectors, s.uncorrectable_sectors, s.media_errors];
  return values.every((v) => v == null) ? null : values.reduce<number>((a, v) => a + (v ?? 0), 0);
}

function errorSummary(d: Disk): string {
  const s = effectiveSample(d);
  if (!s) return "-";
  if (d.disk_type === "nvme") {
    return `media ${formatNumber(s.media_errors)} · istrošenost ${formatNumber(s.percentage_used, "%")}`;
  }
  return `realoc. ${formatNumber(s.reallocated_sectors)} · pending ${formatNumber(s.pending_sectors)} · CRC ${formatNumber(s.crc_errors)}`;
}

const HEALTH_ORDER: Record<string, number> = { critical: 0, endangered: 1, attention: 2, unknown: 3, good: 4, excellent: 5 };
type SortKey = "model" | "device" | "state" | "type" | "capacity" | "temp" | "poh" | "errors" | "read";

const SORTERS: Record<SortKey, (d: Disk) => string | number | null> = {
  model: (d) => d.model ?? "",
  device: (d) => `${d.device_name} ${d.device_path}`,
  state: (d) => HEALTH_ORDER[d.health?.level ?? "unknown"] * 1000 + (d.health?.score ?? 0),
  type: (d) => d.disk_type,
  capacity: (d) => d.capacity_bytes,
  temp: (d) => effectiveSample(d)?.temperature_c ?? null,
  poh: (d) => effectiveSample(d)?.power_on_hours ?? null,
  errors: (d) => errorCount(d),
  read: (d) => d.latest?.collected_at ?? null,
};

const PAGE_SIZE = 50;

export function DiskTable({ disks, showDevice }: { disks: Disk[]; showDevice?: boolean }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "device", dir: 1 });
  const [page, setPage] = useState(0);
  const sorted = useMemo(() => {
    const get = SORTERS[sort.key];
    return [...disks].sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1; // „nema podataka” uvek na kraju
      if (vb == null) return -1;
      return (typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb), "sr")) * sort.dir;
    });
  }, [disks, sort]);
  if (disks.length === 0) return <EmptyState>Nema diskova. Diskovi se pojavljuju posle prvog uspešnog prikupljanja.</EmptyState>;
  const pages = Math.ceil(sorted.length / PAGE_SIZE);
  const current = Math.min(page, pages - 1);
  const visible = sorted.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  const head = (label: string, key: SortKey) => (
    <button
      type="button"
      className="inline-flex items-center gap-0.5 uppercase hover:text-slate-900 dark:hover:text-slate-100"
      onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }))}
      aria-label={`Sortiraj po: ${label}`}
    >
      {label}
      {sort.key === key ? (sort.dir === 1 ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />) : null}
    </button>
  );

  return (
    <>
      <Table
        head={[
          head("Disk", "model"),
          ...(showDevice ? [head("Uređaj", "device")] : []),
          head("Zdravlje", "state"),
          "SMART",
          head("Tip", "type"),
          head("Kapacitet", "capacity"),
          head("Temp.", "temp"),
          head("Rad", "poh"),
          head("Greške", "errors"),
          "Pool",
          head("Očitano", "read"),
        ]}
      >
        {visible.map((d) => {
          const s = effectiveSample(d);
          const standby = d.latest?.smart_health === "standby";
          const smart = s ? SMART_HEALTH[s.smart_health] : null;
          return (
            <tr key={d.id} className={d.is_present ? "" : "opacity-60"}>
              <Td>
                <Link to={`/diskovi/${d.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-500">
                  {d.model ?? "Nepoznat model"}
                </Link>
                <span className="block text-xs text-slate-500">
                  <span className="mono">{d.device_path}</span> · <SerialNumber serial={d.serial_number} />
                </span>
              </Td>
              {showDevice && (
                <Td>
                  <Link to={`/uredjaji/${d.device_id}`} className="hover:underline">{d.device_name}</Link>
                </Td>
              )}
              <Td>
                {d.is_present ? <HealthBadge level={d.health.level} score={d.health.score} /> : <Badge tone="unknown">Nedostaje</Badge>}
                {d.health.reasons.length > 0 && <span className="mt-0.5 block max-w-56 text-xs text-slate-500">{d.health.reasons[0].text.slice(0, 120)}</span>}
              </Td>
              <Td>
                {smart ? <Badge tone={smart.tone}>{smart.label}</Badge> : "-"}
                {standby && <span className="mt-0.5 block"><Badge tone="info">Standby</Badge></span>}
              </Td>
              <Td className="whitespace-nowrap">
                {DISK_TYPE[d.disk_type]}
                {d.rotation_rate ? <span className="block text-xs text-slate-500">{d.rotation_rate} rpm</span> : null}
              </Td>
              <Td className="whitespace-nowrap">{formatCapacity(d.capacity_bytes)}</Td>
              <Td><Temperature value={s?.temperature_c} /></Td>
              <Td className="whitespace-nowrap">{formatHours(s?.power_on_hours)}</Td>
              <Td className="whitespace-nowrap text-xs">{errorSummary(d)}</Td>
              <Td className="text-xs">{d.pools.join(", ") || "-"}</Td>
              <Td className="whitespace-nowrap text-xs" >
                <span title={formatDateTime(d.latest?.collected_at)}>{formatRelative(d.latest?.collected_at)}</span>
              </Td>
            </tr>
          );
        })}
      </Table>
      {pages > 1 && (
        <div className="mt-3 flex items-center justify-end gap-2 text-sm">
          <span className="text-slate-500">
            {current * PAGE_SIZE + 1}-{Math.min(sorted.length, (current + 1) * PAGE_SIZE)} od {sorted.length}
          </span>
          <Button size="sm" disabled={current === 0} onClick={() => setPage(current - 1)}>Prethodna</Button>
          <Button size="sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Sledeća</Button>
        </div>
      )}
    </>
  );
}

function memberTone(state: string | null) {
  if (!state) return "unknown" as const;
  if (["ONLINE", "AVAIL", "INUSE", "SPARE"].includes(state)) return "ok" as const;
  if (["DEGRADED", "WRITEMOSTLY", "REPLACEMENT"].includes(state)) return "warning" as const;
  return "critical" as const;
}

export function PoolCard({ pool, showDevice, link = true }: { pool: Pool; showDevice?: boolean; link?: boolean }) {
  const tone = poolTone(pool);
  const details = pool.details as Record<string, number | string | boolean | null>;
  const members = pool.members.filter((m) => m.kind !== "group" || pool.members.length > 1);
  const errors = (pool.read_errors ?? 0) + (pool.write_errors ?? 0) + (pool.checksum_errors ?? 0);
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div>
          <h3 className="font-semibold">
            {link ? <Link to={`/skladiste/${pool.id}`} className="text-brand-700 hover:underline dark:text-brand-500">{pool.name}</Link> : pool.name}
            {details.system ? <span className="ml-2 text-xs font-normal text-slate-500">(sistemski)</span> : null}
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {POOL_TECH[pool.technology]}
            {typeof details.type === "string" ? ` · ${details.type}` : ""}
            {pool.redundancy ? ` · ${pool.redundancy}` : ""}
            {showDevice ? ` · ${pool.device_name}` : ""}
          </p>
        </div>
        <Badge tone={tone.tone}>{tone.label}</Badge>
      </header>
      <div className="space-y-3 p-4 text-sm">
        <UsageBar used={pool.used_bytes} total={pool.capacity_bytes} allocation={pool.technology === "lvm_vg"} />
        {pool.redundancy === "stripe" && (
          <Alert tone="warning">Pool nema redundansu: kvar bilo kog diska znači gubitak podataka u celom pool-u.</Alert>
        )}
        {pool.message && pool.healthy === false && <Alert tone="critical">{pool.message}</Alert>}
        {pool.message && pool.healthy !== false && <p className="text-xs text-slate-500 dark:text-slate-400">Poruka sistema: {pool.message}</p>}
        {pool.data_errors && pool.technology === "zfs" && pool.data_errors !== "No known data errors" && (
          <Alert tone="critical" title="Greške podataka">{pool.data_errors}</Alert>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {pool.technology === "zfs" && (
            <>
              <dt className="text-slate-500">Greške (R/W/CKSUM)</dt>
              <dd className={errors ? "font-semibold text-red-600 dark:text-red-400" : ""}>
                {formatNumber(pool.read_errors)} / {formatNumber(pool.write_errors)} / {formatNumber(pool.checksum_errors)}
              </dd>
            </>
          )}
          {(pool.scan_type || pool.scan_state === "none") && (
            <>
              <dt className="text-slate-500">{pool.scan_type ? SCAN_LABEL[pool.scan_type] ?? pool.scan_type : "Scrub"}</dt>
              <dd>
                {pool.scan_state === "in_progress" && `u toku${pool.scan_progress != null ? ` - ${pool.scan_progress.toLocaleString("sr-Latn")}%` : ""}`}
                {pool.scan_state === "finished" && (
                  <>
                    završen {pool.scan_finished_at ?? ""}
                    {pool.scan_errors != null && (
                      <span className={pool.scan_errors ? "font-semibold text-red-600 dark:text-red-400" : ""}> · grešaka: {pool.scan_errors}</span>
                    )}
                  </>
                )}
                {pool.scan_state === "none" && "nikad pokrenut"}
                {pool.scan_state === "canceled" && "prekinut"}
                {pool.scan_state === "paused" && "pauziran"}
              </dd>
            </>
          )}
          {typeof details.fragmentation_percent === "number" && (
            <>
              <dt className="text-slate-500">Fragmentacija</dt>
              <dd>{details.fragmentation_percent}%</dd>
            </>
          )}
          {typeof details.metadata_percent === "number" && (
            <>
              <dt className="text-slate-500">Metapodaci</dt>
              <dd>{details.metadata_percent.toLocaleString("sr-Latn")}%</dd>
            </>
          )}
          {typeof details.thin_volumes === "number" && (
            <>
              <dt className="text-slate-500">Thin volumena</dt>
              <dd>{details.thin_volumes}</dd>
            </>
          )}
          <dt className="text-slate-500">Očitano</dt>
          <dd>{formatDateTime(pool.last_seen_at)}</dd>
        </dl>
        {members.length > 0 && (
          <Table head={["Član", "Stanje", "R", "W", "CKSUM"]}>
            {members.map((m, i) => (
              <tr key={`${m.name}-${i}`}>
                <Td>
                  <span style={{ paddingLeft: `${Math.max(0, m.depth - 1) * 16}px` }} className={m.kind === "disk" ? "mono" : "font-medium"}>
                    {m.disk_id ? (
                      <Link to={`/diskovi/${m.disk_id}`} className="text-brand-700 hover:underline dark:text-brand-500">{m.disk_path ?? m.name}</Link>
                    ) : (
                      m.disk_path ?? m.name
                    )}
                  </span>
                  {m.disk_path && m.disk_path !== m.name && <span className="mono ml-2 break-all text-xs text-slate-500">{m.name}</span>}
                  {m.note && <span className="ml-2 text-xs text-amber-700 dark:text-amber-400">{m.note}</span>}
                </Td>
                <Td>{m.state ? <Badge tone={memberTone(m.state)}>{m.state}</Badge> : null}</Td>
                <Td>{m.read_errors ?? ""}</Td>
                <Td>{m.write_errors ?? ""}</Td>
                <Td className={m.checksum_errors ? "font-semibold text-red-600 dark:text-red-400" : ""}>{m.checksum_errors ?? ""}</Td>
              </tr>
            ))}
          </Table>
        )}
      </div>
    </section>
  );
}
