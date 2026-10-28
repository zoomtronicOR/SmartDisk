import { useQuery } from "@tanstack/react-query";
import { Clock as ClockIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";
import { useClickBurst } from "./clickBurst";

const BIG_MS = 30_000;

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
  // Skrivena šala: 5 uzastopnih klikova uveća sat preko ekrana na 30 sekundi
  const [big, setBig] = useState(false);
  const onClick = useClickBurst(() => setBig(true));
  useEffect(() => {
    if (!big) return;
    const id = window.setTimeout(() => setBig(false), BIG_MS);
    return () => window.clearTimeout(id);
  }, [big]);
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
    <>
    <span onClick={onClick} className={`flex select-none items-center gap-1.5 whitespace-nowrap text-sm tabular-nums ${problem ? "text-amber-700 dark:text-amber-400" : "text-slate-600 dark:text-slate-300"}`} title={title}>
      <ClockIcon className="size-4" aria-hidden />
      <span className="hidden md:inline">{date}</span>
      <span className="font-medium">{clock}</span>
      {problem && <span className="text-xs">(NTP!)</span>}
    </span>
    {big && createPortal(
      <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-6 bg-white/95 p-4 text-center dark:bg-slate-950/95" role="alert">
        <p className="text-3xl font-black uppercase tracking-wide text-red-600 sm:text-5xl dark:text-red-400">HOĆEŠ DA KLIKĆEŠ, EVO TI SAD!</p>
        <p className="text-[18vw] font-bold leading-none tabular-nums text-slate-900 dark:text-slate-100">{clock}</p>
        <p className="text-xl text-slate-500 sm:text-3xl">{date}</p>
      </div>,
      document.body,
    )}
    </>
  );
}
