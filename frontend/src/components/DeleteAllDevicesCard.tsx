import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { Device } from "../types";
import { Alert, Button, Card, ErrorText, Field, Input, Modal } from "./ui";

/** Brisanje svih uređaja odjednom (npr. kontejner premešten u drugu mrežu). Potvrda lozinkom administratora. */
export default function DeleteAllDevicesCard() {
  const queryClient = useQueryClient();
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api<Device[]>("/devices", { background: true }) });
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  const count = devices.data?.length ?? 0;

  const close = () => {
    setOpen(false);
    setPassword("");
    setError(null);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ deleted: number; alarms_resolved: number }>("/devices/delete-all", { method: "POST", body: { password } });
      close();
      setMessage(`Obrisano uređaja: ${res.deleted}. Zatvoreno alarma: ${res.alarms_resolved}.`);
      await queryClient.invalidateQueries();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Brisanje svih uređaja">
      <div className="space-y-3 text-sm">
        <p className="text-slate-600 dark:text-slate-300">
          Uklanja sve nadzirane uređaje odjednom, na primer kada je kontejner premešten u drugu mrežu, pa treba dodati uređaje iz nove mreže.
          Istorija diskova ostaje u bazi, kao i kod brisanja jednog uređaja.
        </p>
        {message && <Alert tone="ok">{message}</Alert>}
        <Button variant="danger" icon={<Trash2 className="size-4" />} disabled={count === 0} onClick={() => { setMessage(null); setOpen(true); }}>
          Obriši sve uređaje{count > 0 ? ` (${count})` : ""}
        </Button>
        {count === 0 && devices.data && <p className="text-slate-500">Nema uređaja za brisanje.</p>}
      </div>

      {open && (
        <Modal title="Brisanje svih uređaja" onClose={close}>
          <form
            className="space-y-3 text-sm"
            onSubmit={(e) => {
              e.preventDefault();
              if (password) void submit();
            }}
          >
            <Alert tone="critical">
              Biće obrisano uređaja: <b>{count}</b>. Ova radnja se ne može poništiti.
            </Alert>
            <ul className="list-disc space-y-1 pl-5 text-slate-600 dark:text-slate-300">
              <li>uređaji se više ne kontaktiraju i nestaju sa svih ekrana;</li>
              <li>privatni SSH ključevi uređaja se brišu iz aplikacije;</li>
              <li>aktivni alarmi tih uređaja se zatvaraju;</li>
              <li>istorija diskova, izveštaji i audit log ostaju.</li>
            </ul>
            <p className="text-slate-500">
              Na samim serverima nalog <code>diskmonitor</code> i javni ključ ostaju. Uklonite ih ručno ako se server više neće nadzirati.
            </p>
            <Field label="Vaša lozinka (potvrda)">
              <Input type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <ErrorText error={error} />
            <div className="flex justify-end gap-2">
              <Button type="button" onClick={close}>Otkaži</Button>
              <Button type="submit" variant="danger" loading={busy} disabled={!password} icon={<Trash2 className="size-4" />}>
                Obriši sve uređaje
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </Card>
  );
}
