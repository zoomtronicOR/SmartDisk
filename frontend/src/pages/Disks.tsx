import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { DiskTable, effectiveSample } from "../components/storage";
import { Card, ErrorText, Input, Select, Spinner } from "../components/ui";
import { DISK_STATE, DISK_TYPE, SMART_HEALTH } from "../format";
import type { Disk, DiskState, DiskType, SmartHealth } from "../types";

export default function DisksPage() {
  const disks = useQuery({
    queryKey: ["disks"],
    queryFn: () => api<Disk[]>("/disks", { background: true }),
    refetchInterval: 30_000,
  });
  const [device, setDevice] = useState("");
  const [state, setState] = useState<"" | DiskState>("");
  const [type, setType] = useState<"" | DiskType>("");
  const [smart, setSmart] = useState<"" | SmartHealth>("");
  const [presence, setPresence] = useState<"" | "present" | "missing">("present");
  const [search, setSearch] = useState("");

  const devices = useMemo(() => {
    const map = new Map<number, string>();
    for (const d of disks.data ?? []) map.set(d.device_id, d.device_name);
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [disks.data]);

  const filtered = (disks.data ?? []).filter((d) => {
    if (device && String(d.device_id) !== device) return false;
    if (state && d.state !== state) return false;
    if (type && d.disk_type !== type) return false;
    if (smart && effectiveSample(d)?.smart_health !== smart && d.latest?.smart_health !== smart) return false;
    if (presence === "present" && !d.is_present) return false;
    if (presence === "missing" && d.is_present) return false;
    if (search) {
      const q = search.toLowerCase();
      const text = [d.model, d.vendor, d.device_path, d.serial_number, d.device_name, d.pools.join(" ")].join(" ").toLowerCase();
      if (!text.includes(q)) return false;
    }
    return true;
  });

  if (disks.isLoading) return <Spinner />;
  if (disks.error) return <ErrorText error={disks.error} />;
  const exportBase = `/api/reports/disks?${device ? `device_id=${device}&` : ""}format=`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Diskovi</h1>
        <div className="flex gap-2">
          {(["csv", "xlsx", "pdf"] as const).map((fmt) => (
            <a
              key={fmt}
              href={exportBase + fmt}
              download
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-sm hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-900 dark:hover:bg-slate-800"
            >
              <Download className="size-4" /> {fmt.toUpperCase()}
            </a>
          ))}
        </div>
      </div>
      <Card>
        <div className="mb-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <Select value={device} onChange={(e) => setDevice(e.target.value)} aria-label="Uređaj">
            <option value="">Svi uređaji</option>
            {devices.map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </Select>
          <Select value={state} onChange={(e) => setState(e.target.value as "" | DiskState)} aria-label="Stanje">
            <option value="">Sva stanja</option>
            {(Object.keys(DISK_STATE) as DiskState[]).map((s) => (
              <option key={s} value={s}>{DISK_STATE[s].label}</option>
            ))}
          </Select>
          <Select value={smart} onChange={(e) => setSmart(e.target.value as "" | SmartHealth)} aria-label="SMART status">
            <option value="">SMART: svi</option>
            {(Object.keys(SMART_HEALTH) as SmartHealth[]).map((s) => (
              <option key={s} value={s}>SMART: {SMART_HEALTH[s].label}</option>
            ))}
          </Select>
          <Select value={type} onChange={(e) => setType(e.target.value as "" | DiskType)} aria-label="Tip diska">
            <option value="">Svi tipovi</option>
            {(Object.keys(DISK_TYPE) as DiskType[]).map((t) => (
              <option key={t} value={t}>{DISK_TYPE[t]}</option>
            ))}
          </Select>
          <Select value={presence} onChange={(e) => setPresence(e.target.value as "" | "present" | "missing")} aria-label="Prisutnost">
            <option value="present">Prisutni</option>
            <option value="missing">Nestali</option>
            <option value="">Prisutni i nestali</option>
          </Select>
          <Input placeholder="Pretraga…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Pretraga: model, putanja, serijski broj, pool" />
        </div>
        <DiskTable disks={filtered} showDevice />
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          Prikazano {filtered.length} od {disks.data?.length ?? 0}. Klik na naslov kolone sortira. Stanje se zasniva na SMART statusu i ključnim brojačima;
          za disk u standby-ju prikazane su vrednosti iz poslednjeg SMART očitavanja. Ocena „Zdravlje diska” sa trendovima stiže u Fazi 4.
        </p>
      </Card>
    </div>
  );
}
