import { useQueryClient } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { collectClientInfo } from "../clientInfo";
import { Button, ErrorText, Field, Input } from "../components/ui";
import type { User } from "../types";

export default function LoginPage() {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const client = await collectClientInfo().catch(() => ({}));
      const user = await api<User>("/auth/login", { method: "POST", body: { username, password, client } });
      queryClient.setQueryData(["me"], user);
    } catch (err) {
      setError(err);
      setPassword("");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-2">
          <HardDrive className="size-7 text-brand-600" />
          <div>
            <h1 className="text-xl font-semibold">SmartDisk</h1>
            <p className="text-sm text-slate-500">Nadzor diskova i skladišta</p>
          </div>
        </div>
        <Field label="Korisničko ime">
          <Input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </Field>
        <Field label="Lozinka">
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <ErrorText error={error} />
        <Button type="submit" variant="primary" className="w-full" loading={loading}>
          Prijava
        </Button>
      </form>
    </div>
  );
}
