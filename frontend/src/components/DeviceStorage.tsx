import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { Disk, Platform, Pool, PrivilegeProfile } from "../types";
import { DiskTable, PoolCard } from "./storage";
import { Card, CopyButton, EmptyState, Spinner } from "./ui";

/** Diskovi i skladište jednog uređaja (stranica uređaja). */
export function DeviceStorage({ deviceId }: { deviceId: number }) {
  const disks = useQuery({
    queryKey: ["disks", { device: deviceId }],
    queryFn: () => api<Disk[]>(`/disks?device_id=${deviceId}`, { background: true }),
    refetchInterval: 30_000,
  });
  const pools = useQuery({
    queryKey: ["pools", { device: deviceId }],
    queryFn: () => api<Pool[]>(`/pools?device_id=${deviceId}`, { background: true }),
    refetchInterval: 30_000,
  });
  return (
    <>
      <Card title={`Diskovi${disks.data ? ` (${disks.data.filter((d) => d.is_present).length})` : ""}`}>
        {disks.isLoading ? <Spinner /> : <DiskTable disks={disks.data ?? []} />}
      </Card>
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Skladište</h2>
        {pools.isLoading && <Spinner />}
        {pools.data && pools.data.length === 0 && (
          <Card>
            <EmptyState>Nema podataka o skladištu (ZFS, LVM, RAID).</EmptyState>
          </Card>
        )}
        <div className="grid gap-4 xl:grid-cols-2">
          {pools.data?.map((pool) => <PoolCard key={pool.id} pool={pool} />)}
        </div>
      </div>
    </>
  );
}

/** Tačan profil privilegija za namenski nalog na uređaju (spec. 5.3). */
export function PrivilegeProfileCard({ platform, username }: { platform: Platform; username: string }) {
  const profile = useQuery({
    queryKey: ["privileges", platform],
    queryFn: () => api<PrivilegeProfile>(`/platforms/${platform}/privileges`),
  });
  const sudoers = profile.data?.sudoers.replace(/^diskmonitor /m, `${username} `).replaceAll(":diskmonitor ", `:${username} `).replaceAll("nalog diskmonitor", `nalog ${username}`);
  return (
    <Card title="Profil privilegija za nalog na uređaju">
      {profile.isLoading || !profile.data ? (
        <Spinner />
      ) : (
        <details className="space-y-3 text-sm">
          <summary className="cursor-pointer select-none text-brand-700 dark:text-brand-500">
            Prikaži tačne komande i sudoers profil ({profile.data.sudo_commands.length} komandi sa sudo, sve read-only)
          </summary>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300">
            {profile.data.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
          <div className="flex items-center justify-between">
            <p className="font-medium">sudoers profil</p>
            <CopyButton text={sudoers ?? ""} />
          </div>
          <pre className="max-h-80 overflow-auto rounded bg-slate-100 p-3 text-xs dark:bg-slate-950">{sudoers}</pre>
          {platform.startsWith("truenas") && (
            <>
              <div className="flex items-center justify-between">
                <p className="font-medium">Komande za TrueNAS polje „sudo commands” (jedna po redu)</p>
                <CopyButton text={profile.data.sudo_commands.join("\n")} />
              </div>
              <pre className="max-h-60 overflow-auto rounded bg-slate-100 p-3 text-xs dark:bg-slate-950">{profile.data.sudo_commands.join("\n")}</pre>
            </>
          )}
          <p className="text-slate-500 dark:text-slate-400">Bez sudo-a (običan korisnik): {profile.data.unprivileged.join(" · ")}</p>
        </details>
      )}
    </Card>
  );
}
