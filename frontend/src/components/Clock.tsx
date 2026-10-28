import { useQuery } from "@tanstack/react-query";
import { Clock as ClockIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";

export type TimeInfo = {
  server_time: string;
  timezone: string;
  ntp_server: string;
  checked_at: string | null;
  offset_ms: number | null;
  delay_ms: number | null;
  stratum: number | null;
  host_synchronized: boolean | null;
  error: string | null;
};

/**
 * Datum i vreme u zaglavlju (spec. §18.1), u vremenskoj zoni prikaza. Prikazuje se vreme servera:
 * razlika sata pregledača i servera se meri pri učitavanju, pa pogrešan sat računara ne menja prikaz.
 */
export default function Clock() {
  const time = useQuery({
    queryKey: ["system-time"],
    queryFn: async () => {
      const sent = Date.now();
      const data = await api<TimeInfo>("/system/time", { background: true });
      const received = Date.now();
      return { ...data, skew: new Date(data.server_time).getTime() - (sent + received) / 2 };
    },
    refetchInterval: 5 * 60_000,
  });
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  if (!time.data) return null;
  const t = time.data;
  const serverNow = new Date(now + (Number.isFinite(t.skew) ? t.skew : 0));
  const tz = t.timezone;
  const date = new Intl.DateTimeFormat("sr-Latn-RS", { timeZone: tz, weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" }).format(serverNow);
  const clock = new Intl.DateTimeFormat("sr-Latn-RS", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(serverNow);
  const problem = t.error !== null || t.host_synchronized === false || (t.offset_ms !== null && Math.abs(t.offset_ms) >= 2000);
  const title = problem
    ? `Vreme servera nije pouzdano: ${t.error ?? (t.host_synchronized === false ? "nije sinhronizovano sa NTP-om" : `odstupanje ${t.offset_ms} ms od ${t.ntp_server}`)}`
    : `Vreme servera (${tz}). NTP: ${t.ntp_server}${t.offset_ms !== null ? `, odstupanje ${t.offset_ms} ms` : ""}`;
  return (
    <span className={`flex items-center gap-1.5 whitespace-nowrap text-sm tabular-nums ${problem ? "text-amber-700 dark:text-amber-400" : "text-slate-600 dark:text-slate-300"}`} title={title}>
      <ClockIcon className="size-4" aria-hidden />
      <span className="hidden md:inline">{date}</span>
      <span className="font-medium">{clock}</span>
      {problem && <span className="text-xs">(NTP!)</span>}
    </span>
  );
}
