import { useQuery } from "@tanstack/react-query";
import { Angry, BellRing, ChartLine, CircleHelp, Columns3, Database, Network, FileText, HardDrive, LayoutDashboard, LogOut, Menu, Moon, ScrollText, Server, Settings, Sun, UserCircle, Users } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ROLE_LABELS, setDisplayTimezone } from "../format";
import type { AlarmSummary, SystemStatus } from "../types";
import { useBranding } from "./BrandingCard";
import Clock from "./Clock";
import { Alert, Spinner } from "./ui";

const ANGRY_CLICKS = 5;
const ANGRY_GAP_MS = 1500;
const ANGRY_MS = 5 * 60_000;

/** Naslov u sidebaru. Skrivena šala: 5 uzastopnih klikova prikazuje ljutog smajlija na 5 minuta. */
function AppTitle() {
  const [until, setUntil] = useState(() => {
    try {
      return Number(localStorage.getItem("sd-angry")) || 0;
    } catch {
      return 0;
    }
  });
  const clicks = useRef({ count: 0, last: 0 });
  const angry = until > Date.now();

  useEffect(() => {
    if (!angry) return;
    const t = setTimeout(() => setUntil(0), until - Date.now());
    return () => clearTimeout(t);
  }, [angry, until]);

  const onClick = () => {
    const now = Date.now();
    const c = clicks.current;
    c.count = now - c.last <= ANGRY_GAP_MS ? c.count + 1 : 1;
    c.last = now;
    if (c.count < ANGRY_CLICKS) return;
    c.count = 0;
    const next = now + ANGRY_MS;
    setUntil(next);
    try {
      localStorage.setItem("sd-angry", String(next));
    } catch {
      // bez localStorage smajli traje samo dok je stranica otvorena
    }
  };

  return (
    <span className="flex select-none items-center gap-1.5 text-lg font-semibold" onClick={onClick}>
      SmartDisk
      {angry && <Angry className="size-5 text-red-600 dark:text-red-400" aria-label="Ljuti smajli" />}
    </span>
  );
}

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("sd-theme", next ? "dark" : "light");
    } catch {
      /* lokalno skladište nije dostupno */
    }
  };
  return { dark, toggle };
}

export default function Layout() {
  const { user, logout } = useAuth();
  const { dark, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMenuOpen(false), [location.pathname]);

  const general = useQuery({ queryKey: ["settings", "general"], queryFn: () => api<{ timezone: string }>("/settings/general") });
  if (general.data) setDisplayTimezone(general.data.timezone);

  const system = useQuery({
    queryKey: ["system"],
    queryFn: () => api<SystemStatus>("/system/status", { background: true }),
    refetchInterval: 30_000,
  });

  const branding = useBranding();
  const alarms = useQuery({
    queryKey: ["alarm-summary"],
    queryFn: () => api<AlarmSummary>("/alarms/summary", { background: true }),
    refetchInterval: 30_000,
  });

  const admin = user?.role === "admin";
  const nav = [
    { to: "/", label: "Pregled", icon: LayoutDashboard, end: true },
    { to: "/alarmi", label: "Alarmi", icon: BellRing, badge: true },
    { to: "/uredjaji", label: "Uređaji", icon: Server },
    { to: "/diskovi", label: "Diskovi", icon: HardDrive },
    { to: "/skladiste", label: "Skladište", icon: Database },
    { to: "/mapa", label: "Mapa skladišta", icon: Network },
    { to: "/poredjenje", label: "Poređenje", icon: Columns3 },
    { to: "/statistika", label: "Statistika", icon: ChartLine },
    { to: "/izvestaji", label: "Izveštaji", icon: FileText },
    ...(admin
      ? [
          { to: "/korisnici", label: "Korisnici", icon: Users },
          { to: "/podesavanja", label: "Podešavanja", icon: Settings },
          { to: "/audit", label: "Audit log", icon: ScrollText },
        ]
      : []),
    { to: "/nalog", label: "Moj nalog", icon: UserCircle },
    { to: "/pomoc", label: "Pomoć", icon: CircleHelp },
  ];

  return (
    <div className="flex min-h-screen">
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white transition-transform dark:border-slate-800 dark:bg-slate-900 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          menuOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2 px-5 py-4">
          <HardDrive className="size-6 text-brand-600" />
          <AppTitle />
        </div>
        <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-3">
          {nav.map(({ to, label, icon: Icon, end, badge }: { to: string; label: string; icon: typeof Server; end?: boolean; badge?: boolean }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`
              }
            >
              <Icon className="size-4" /> {label}
              {badge && (alarms.data?.total_active ?? 0) > 0 && (
                <span
                  className={`ml-auto rounded-full px-1.5 text-xs font-semibold text-white ${(alarms.data!.active.critical + alarms.data!.active.high) > 0 ? "bg-red-600" : "bg-amber-600"}`}
                  aria-label={`${alarms.data!.total_active} aktivnih alarma`}
                >
                  {alarms.data!.total_active}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        {/* Dno menija: verzija, ispod nje logo kompanije (Podešavanja → Izgled) */}
        <div className="shrink-0 space-y-2 border-t border-slate-200 px-5 py-3 dark:border-slate-800">
          {system.data && <p className="text-xs text-slate-400">Verzija {system.data.version}</p>}
          {branding.data?.has_logo ? (
            <img
              src={`/api/branding/logo?v=${branding.data.version}`}
              alt={branding.data.company_name || "Logo kompanije"}
              title={branding.data.company_name || undefined}
              className="max-h-16 w-full object-contain object-left"
            />
          ) : branding.data?.company_name ? (
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">{branding.data.company_name}</p>
          ) : null}
        </div>
      </aside>
      {menuOpen && <div className="fixed inset-0 z-30 bg-slate-950/40 lg:hidden" onClick={() => setMenuOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-2 border-b border-slate-200 bg-white/90 px-4 py-2.5 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
          <button className="rounded p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Meni">
            <Menu className="size-5" />
          </button>
          <Clock />
          <div className="flex-1" />
          <span className="hidden text-sm text-slate-600 dark:text-slate-300 sm:inline">
            {user?.username} · {user && ROLE_LABELS[user.role]}
          </span>
          <button onClick={toggle} className="rounded p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label={dark ? "Svetla tema" : "Tamna tema"} title={dark ? "Svetla tema" : "Tamna tema"}>
            {dark ? <Sun className="size-5" /> : <Moon className="size-5" />}
          </button>
          <button onClick={logout} className="flex items-center gap-1 rounded px-2 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
            <LogOut className="size-4" /> Odjava
          </button>
        </header>

        <main className="mx-auto w-full max-w-7xl flex-1 space-y-4 p-4 lg:p-6">
          {system.isError && <Alert tone="critical" title="Server nije dostupan">Podaci na ekranu možda nisu aktuelni.</Alert>}
          {system.data && !system.data.scheduler_running && (
            <Alert tone="critical" title="Scheduler ne radi">
              Podaci se trenutno ne prikupljaju. Proverite servis smartdisk-api (journalctl -u smartdisk-api).
            </Alert>
          )}
          <Suspense fallback={<Spinner />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
