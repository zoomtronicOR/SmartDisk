import { CheckCircle2, CircleHelp, Info, Loader2, OctagonAlert, TriangleAlert, X } from "lucide-react";
import { useEffect, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import type { Tone } from "../format";

function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
};

export function Button({ variant = "secondary", size = "md", loading, icon, children, className, disabled, ...rest }: ButtonProps) {
  const variants = {
    primary: "bg-brand-700 text-white hover:bg-brand-600 border-transparent",
    secondary:
      "bg-white text-slate-700 border-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600 dark:hover:bg-slate-700",
    danger: "bg-red-600 text-white hover:bg-red-500 border-transparent",
    ghost: "bg-transparent border-transparent text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
  };
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-sm" : "px-3.5 py-2 text-sm",
        variants[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

const fieldClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-900";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(fieldClass, props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(fieldClass, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(fieldClass, "mono", props.className)} />;
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="block text-sm font-medium text-slate-700 dark:text-slate-300">{label}</span>
      {children}
      {hint && <span className="block text-xs text-slate-500 dark:text-slate-400">{hint}</span>}
    </label>
  );
}

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 className="font-semibold">{title}</h2>
          <div className="flex flex-wrap gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const toneStyles: Record<Tone, { cls: string; Icon: typeof Info }> = {
  ok: { cls: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300", Icon: CheckCircle2 },
  warning: { cls: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300", Icon: TriangleAlert },
  critical: { cls: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300", Icon: OctagonAlert },
  unknown: { cls: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300", Icon: CircleHelp },
  info: { cls: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300", Icon: Info },
};

/** Status se uvek prikazuje bojom, ikonom i tekstom - boja nikad nije jedini nosilac informacije. */
export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  const { cls, Icon } = toneStyles[tone];
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", cls)}>
      <Icon className="size-3.5" aria-hidden />
      {children}
    </span>
  );
}

export function Alert({ tone, title, children }: { tone: Tone; title?: string; children?: ReactNode }) {
  const { cls, Icon } = toneStyles[tone];
  return (
    <div className={cx("flex gap-2 rounded-lg px-3 py-2 text-sm", cls)} role={tone === "critical" ? "alert" : "status"}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div>{children}</div>}
      </div>
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/50 p-4 sm:items-center" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cx("w-full rounded-xl bg-white shadow-xl dark:bg-slate-900", wide ? "max-w-2xl" : "max-w-md")}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 className="font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Zatvori">
            <X className="size-5" />
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ label = "Učitavanje…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-4 text-sm text-slate-500">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="p-6 text-center text-sm text-slate-500 dark:text-slate-400">{children}</p>;
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          const area = document.createElement("textarea");
          area.value = text;
          document.body.appendChild(area);
          area.select();
          document.execCommand("copy");
          area.remove();
        }
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? "Kopirano" : "Kopiraj"}
    </Button>
  );
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cx("px-3 py-2 align-top", className)}>{children}</td>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <Alert tone="critical">{error instanceof Error ? error.message : String(error)}</Alert>;
}

export function Stat({ label, value, tone, sub }: { label: string; value: ReactNode; tone?: Tone; sub?: ReactNode }) {
  const accent = tone ? toneStyles[tone].cls.split(" ").filter((c) => c.startsWith("text-") || c.startsWith("dark:text-")).join(" ") : "";
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-sm text-slate-500 dark:text-slate-400">{label}</p>
      <p className={cx("mt-1 text-2xl font-semibold", accent)}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{sub}</p>}
    </div>
  );
}
