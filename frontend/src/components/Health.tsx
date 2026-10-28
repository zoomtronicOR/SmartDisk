import { useQuery } from "@tanstack/react-query";
import { HeartPulse } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ALARM_STATUS, HEALTH, SEVERITY, SMART_HEALTH, formatDateTime, formatRelative } from "../format";
import type { Alarm, Disk, HealthLevel } from "../types";
import { Alert, Badge, Card, Table, Td } from "./ui";

// Isto kao RECOMMENDATIONS u backend/app/health.py (spec. §8.12).
const RECOMMENDATIONS: Partial<Record<HealthLevel, string[]>> = {
  attention: ["Pratiti disk: proveriti trend u narednim danima.", "Proveriti da li postoji ažurna rezervna kopija."],
  endangered: ["Ne koristiti disk za nove kritične podatke.", "Pripremiti zamenski disk.", "Pokrenuti ili proveriti rezervnu kopiju."],
  critical: [
    "Odmah proveriti rezervnu kopiju podataka.",
    "Zameniti disk što pre (ručno, kroz sistem uređaja – aplikacija ništa ne menja na skladištu).",
    "Ako je disk u ZFS/RAID nizu, pratiti resilver/rebuild posle zamene.",
  ],
  unknown: ["Proveriti zašto podaci nisu dostupni (veza, SMART podrška, kontroler)."],
};

export function HealthBadge({ level, score }: { level: HealthLevel; score?: number | null }) {
  const h = HEALTH[level] ?? HEALTH.unknown;
  return (
    <Badge tone={h.tone}>
      {h.label}
      {score != null && <span className="opacity-75"> · {score}</span>}
    </Badge>
  );
}

/** Sažetak zdravlja diska (spec. §8.12): SMART status i zdravlje su odvojeni pokazatelji. */
export function DiskHealthCard({ disk }: { disk: Disk }) {
  const h = disk.health;
  const s = disk.latest?.smart_health === "standby" && disk.last_smart ? disk.last_smart : disk.latest;
  const alarms = useQuery({
    queryKey: ["alarms", "disk", disk.id],
    queryFn: () => api<{ items: Alarm[] }>(`/alarms?status=all&disk_id=${disk.id}&limit=20`, { background: true }),
    refetchInterval: 30_000,
  });
  const recs = RECOMMENDATIONS[h.level] ?? [];
  return (
    <Card title={<span className="inline-flex items-center gap-2"><HeartPulse className="size-4" /> Zdravlje diska</span>}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <div>
            <span className="text-slate-500">Zdravlje: </span>
            <HealthBadge level={h.level} score={h.score} />
          </div>
          <div>
            <span className="text-slate-500">SMART status: </span>
            {s ? <Badge tone={SMART_HEALTH[s.smart_health].tone}>{SMART_HEALTH[s.smart_health].label}</Badge> : "—"}
          </div>
          <div className="text-xs text-slate-500">Procenjeno {formatRelative(h.updated_at)} ({formatDateTime(h.updated_at)})</div>
        </div>
        {s?.smart_health === "passed" && ["attention", "endangered", "critical"].includes(h.level) && (
          <Alert tone="warning">SMART status je PASSED, ali istorija pokazuje probleme – zato je zdravlje niže. SMART PASSED ne znači da je disk ispravan.</Alert>
        )}
        {h.reasons.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {h.reasons.map((r, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0">{r.severity in SEVERITY ? <Badge tone={SEVERITY[r.severity].tone}>{SEVERITY[r.severity].label}</Badge> : null}</span>
                <span>{r.text}</span>
              </li>
            ))}
          </ul>
        ) : h.level === "excellent" ? (
          <p className="text-sm text-slate-600 dark:text-slate-300">Nema relevantnih grešaka, trend je stabilan, temperatura je normalna.</p>
        ) : null}
        {recs.length > 0 && (
          <div className="rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-800">
            <p className="mb-1 font-medium">Preporuka</p>
            <ul className="list-disc space-y-0.5 pl-5">{recs.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}
        {alarms.data && alarms.data.items.length > 0 && (
          <Table head={["Alarm", "Nivo", "Status", "Prvi put"]}>
            {alarms.data.items.map((a) => (
              <tr key={a.id}>
                <Td><Link to={`/alarmi/${a.id}`} className="text-brand-700 hover:underline dark:text-brand-500">{a.title}</Link></Td>
                <Td><Badge tone={SEVERITY[a.severity].tone}>{SEVERITY[a.severity].label}</Badge></Td>
                <Td><Badge tone={ALARM_STATUS[a.status].tone}>{ALARM_STATUS[a.status].label}</Badge></Td>
                <Td className="whitespace-nowrap">{formatDateTime(a.first_seen_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
      </div>
    </Card>
  );
}
