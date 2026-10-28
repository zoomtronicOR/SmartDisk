import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageUp, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Alert, Button, Card, ErrorText, Field, Input } from "./ui";

export type Branding = { has_logo: boolean; version: string | null; company_name: string };

export function useBranding() {
  return useQuery({ queryKey: ["branding"], queryFn: () => api<Branding>("/branding", { background: true }), staleTime: 300_000 });
}

/** Logo kompanije za dno menija (Podešavanja → Izgled). */
export default function BrandingCard() {
  const queryClient = useQueryClient();
  const branding = useBranding();
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { if (branding.data) setName(branding.data.company_name); }, [branding.data]);

  const pick = (file: File | undefined) => {
    setError(null);
    setMessage(null);
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      setError(new Error("Dozvoljeni formati su PNG, JPEG i WebP."));
      return;
    }
    if (file.size > 512 * 1024) {
      setError(new Error("Logo je veći od 512 KB. Smanjite sliku."));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setPreview(String(reader.result));
    reader.readAsDataURL(file);
  };

  const run = async (key: string, fn: () => Promise<unknown>, text: string) => {
    setBusy(key);
    setError(null);
    setMessage(null);
    try {
      await fn();
      setPreview(null);
      setMessage(text);
      await queryClient.invalidateQueries({ queryKey: ["branding"] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  const current = branding.data?.has_logo ? `/api/branding/logo?v=${branding.data.version}` : null;
  return (
    <Card title="Izgled – logo kompanije">
      <div className="max-w-2xl space-y-3 text-sm">
        <p className="text-slate-500">Logo se prikazuje na dnu menija, ispod oznake verzije. Preporuka: širok logo (npr. 400×120 px) sa providnom pozadinom, PNG, JPEG ili WebP do 512 KB.</p>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex h-20 w-56 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 p-2 dark:border-slate-600 dark:bg-slate-950">
            {preview || current ? (
              <img src={preview ?? current!} alt={name || "Logo kompanije"} className="max-h-full max-w-full object-contain" />
            ) : (
              <span className="text-xs text-slate-400">Logo nije postavljen</span>
            )}
          </div>
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800">
            <ImageUp className="size-4" /> Izaberi sliku…
            <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => pick(e.target.files?.[0])} />
          </label>
        </div>
        <Field label="Naziv kompanije" hint="Koristi se kao opis slike (za čitače ekrana) i kada logo nije postavljen.">
          <Input className="max-w-sm" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} />
        </Field>
        {message && <Alert tone="ok">{message}</Alert>}
        <ErrorText error={error} />
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" loading={busy === "save"} onClick={() => run("save", () => api("/branding", { method: "PUT", body: { data_base64: preview, company_name: name } }), preview ? "Logo je postavljen." : "Sačuvano.")}>
            Sačuvaj
          </Button>
          {preview && <Button onClick={() => setPreview(null)}>Odustani od nove slike</Button>}
          {branding.data?.has_logo && !preview && (
            <Button variant="ghost" icon={<Trash2 className="size-4" />} loading={busy === "del"} onClick={() => run("del", () => api("/branding/logo", { method: "DELETE" }), "Logo je uklonjen.")}>
              Ukloni logo
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
