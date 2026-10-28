import { useQuery } from "@tanstack/react-query";
import { HardDrive, Server } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { HealthBadge } from "../components/Health";
import { Alert, Badge, Spinner } from "../components/ui";
import { DEVICE_STATUS, POOL_TECH, formatCapacity, poolTone } from "../format";
import type { Device, Disk, Pool, PoolMember } from "../types";

function memberTone(state: string | null) {
  if (!state) return "unknown" as const;
  if (["ONLINE", "AVAIL", "INUSE", "SPARE"].includes(state)) return "ok" as const;
  if (state === "DEGRADED") return "warning" as const;
  return "critical" as const;
}

function DiskChip({ disk, member }: { disk?: Disk; member?: PoolMember }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-900">
      <HardDrive className="size-3.5 text-slate-500" aria-hidden />
      {disk ? (
        <Link to={`/diskovi/${disk.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-500">{disk.device_path}</Link>
      ) : (
        <span className="mono">{member?.name}</span>
      )}
      {disk && <span className="text-slate-500">{disk.model} · {formatCapacity(disk.capacity_bytes)}</span>}
      {member?.state && <Badge tone={memberTone(member.state)}>{member.state}</Badge>}
      {disk && <HealthBadge level={disk.health.level} />}
      {member && !disk && <span className="text-slate-500">(disk nije prepoznat)</span>}
    </div>
  );
}

/** Mapa skladišta (spec. §16.3): uređaj → pool/RAID → vdev → diskovi; diskovi van pool-ova posebno. */
export default function StorageMapPage() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices", { background: true }) });
  const disks = useQuery({ queryKey: ["disks"], queryFn: () => api<Disk[]>("/disks", { background: true }) });
  const pools = useQuery({ queryKey: ["pools"], queryFn: () => api<Pool[]>("/pools", { background: true }) });
  if (!devices.data || !disks.data || !pools.data) return <Spinner />;
  const diskById = new Map(disks.data.map((d) => [d.id, d]));

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Mapa skladišta</h1>
      <Alert tone="info">
        Kontroleri (HBA/RAID) se ne prikazuju: platforme ih ne izlažu pouzdano kroz read-only komande. Veza disk ↔ pool se utvrđuje iz imena članova
        (npr. gptid → ada0); ako nije pouzdana, član je označen kao „disk nije prepoznat”.
      </Alert>
      {devices.data.map((dev) => {
        const devPools = pools.data.filter((p) => p.device_id === dev.id && p.is_present && ["zfs", "mdadm", "synology_volume", "lvm_thin"].includes(p.technology));
        const devDisks = disks.data.filter((d) => d.device_id === dev.id && d.is_present);
        const inPool = new Set(devPools.flatMap((p) => p.members.map((m) => m.disk_id).filter(Boolean)));
        const loose = devDisks.filter((d) => !inPool.has(d.id));
        const st = DEVICE_STATUS[dev.status];
        return (
          <section key={dev.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <header className="mb-3 flex flex-wrap items-center gap-2">
              <Server className="size-5 text-brand-600" aria-hidden />
              <Link to={`/uredjaji/${dev.id}`} className="text-lg font-semibold hover:underline">{dev.name}</Link>
              <span className="text-sm text-slate-500">{dev.platform_label} · {dev.host}</span>
              <Badge tone={st.tone}>{st.label}</Badge>
            </header>
            <div className="space-y-3 border-l-2 border-slate-200 pl-4 dark:border-slate-700">
              {devPools.map((p) => {
                const tone = poolTone(p);
                return (
                  <div key={p.id}>
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <Link to={`/skladiste/${p.id}`} className="font-medium hover:underline">{p.name}</Link>
                      <span className="text-xs text-slate-500">{POOL_TECH[p.technology]}{p.redundancy ? ` · ${p.redundancy}` : ""}</span>
                      <Badge tone={tone.tone}>{tone.label}</Badge>
                    </div>
                    <div className="space-y-1 border-l-2 border-slate-100 pl-4 dark:border-slate-800">
                      {p.members.length === 0 && <p className="text-xs text-slate-500">Topologija nije dostupna za ovu vrstu skladišta.</p>}
                      {p.members.map((m, i) =>
                        m.kind === "disk" ? (
                          <div key={i} style={{ marginLeft: `${Math.max(0, m.depth - 1) * 16}px` }}>
                            <DiskChip disk={m.disk_id ? diskById.get(m.disk_id) : undefined} member={m} />
                          </div>
                        ) : (
                          <div key={i} className="flex items-center gap-2 text-sm" style={{ marginLeft: `${Math.max(0, m.depth - 1) * 16}px` }}>
                            <span className="font-medium">{m.name}</span>
                            {m.state && <Badge tone={memberTone(m.state)}>{m.state}</Badge>}
                          </div>
                        ),
                      )}
                    </div>
                  </div>
                );
              })}
              {loose.length > 0 && (
                <div>
                  <p className="mb-1 text-sm font-medium">{devPools.length ? "Diskovi van prikazanih pool-ova" : "Diskovi"}</p>
                  <div className="flex flex-wrap gap-2">{loose.map((d) => <DiskChip key={d.id} disk={d} />)}</div>
                  {dev.platform === "proxmox" && <p className="mt-1 text-xs text-slate-500">Na Proxmoxu veza LVM volume grupe sa fizičkim diskom nije utvrđena (potreban je `pvs`).</p>}
                </div>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
