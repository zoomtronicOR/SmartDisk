import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import PushCard from "../components/PushCard";
import TokensCard from "../components/TokensCard";
import { Alert, Button, Card, ErrorText, Field, Input } from "../components/ui";
import { formatDateTime, ROLE_LABELS } from "../format";

export default function AccountPage({ forced = false }: { forced?: boolean }) {
  const { user, refresh, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(false);
    if (next !== repeat) {
      setError(new Error("Nove lozinke se ne poklapaju."));
      return;
    }
    setLoading(true);
    try {
      await api("/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      setRepeat("");
      setDone(true);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const form = (
    <form onSubmit={submit} className="max-w-md space-y-3">
      <Field label="Trenutna lozinka">
        <Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </Field>
      <Field label="Nova lozinka" hint="Najmanje 10 znakova; kraća od 16 mora imati bar tri vrste znakova (mala, velika slova, cifre, specijalni).">
        <Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
      </Field>
      <Field label="Ponovite novu lozinku">
        <Input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
      </Field>
      <ErrorText error={error} />
      {done && <Alert tone="ok">Lozinka je promenjena. Ostale sesije su odjavljene.</Alert>}
      <Button type="submit" variant="primary" loading={loading}>
        Promeni lozinku
      </Button>
    </form>
  );

  if (forced) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="w-full max-w-md space-y-4">
          <Alert tone="warning" title="Potrebna je nova lozinka">
            Administrator je postavio privremenu lozinku. Pre nastavka rada postavite sopstvenu.
          </Alert>
          <Card title={`Promena lozinke - ${user?.username}`} actions={<Button size="sm" variant="ghost" onClick={logout}>Odjava</Button>}>
            {form}
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Moj nalog</h1>
      <Card title="Podaci">
        <dl className="grid gap-2 text-sm sm:grid-cols-[12rem_1fr]">
          <dt className="text-slate-500">Korisničko ime</dt>
          <dd>{user?.username}</dd>
          <dt className="text-slate-500">Uloga</dt>
          <dd>{user && ROLE_LABELS[user.role]}</dd>
          <dt className="text-slate-500">E-mail</dt>
          <dd>{user?.email || "-"}</dd>
          <dt className="text-slate-500">Poslednja prijava</dt>
          <dd>{formatDateTime(user?.last_login_at)}</dd>
        </dl>
      </Card>
      <Card title="Promena lozinke">{form}</Card>
      <PushCard />
      <TokensCard />
    </div>
  );
}
