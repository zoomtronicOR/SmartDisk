import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Select, Spinner, Table, Td } from "../components/ui";
import { formatDateTime, ROLE_LABELS } from "../format";
import type { Role, User } from "../types";

const PASSWORD_HINT = "Najmanje 10 znakova. Korisnik će morati da je promeni pri prvoj prijavi.";

function UserModal({ user, onClose, onSaved }: { user?: User; onClose: () => void; onSaved: () => void }) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<Role>(user?.role ?? "viewer");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      if (user) {
        await api(`/users/${user.id}`, { method: "PUT", body: { email: email || null, role, is_active: active } });
      } else {
        await api("/users", { method: "POST", body: { username, email: email || null, role, password } });
      }
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={user ? `Izmena – ${user.username}` : "Novi korisnik"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {!user && (
          <Field label="Korisničko ime">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="off" />
          </Field>
        )}
        <Field label="E-mail (opciono)">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Uloga">
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="admin">Administrator – puni pristup</option>
            <option value="operator">Operater – pregled, potvrda alarma, ručno prikupljanje</option>
            <option value="viewer">Pregled – samo čitanje</option>
          </Select>
        </Field>
        {user ? (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Nalog je aktivan
          </label>
        ) : (
          <Field label="Privremena lozinka" hint={PASSWORD_HINT}>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" />
          </Field>
        )}
        <ErrorText error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Otkaži
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            Sačuvaj
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ResetModal({ user, onClose }: { user: User; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  return (
    <Modal title={`Reset lozinke – ${user.username}`} onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setSaving(true);
          setError(null);
          try {
            await api(`/users/${user.id}/reset-password`, { method: "POST", body: { new_password: password } });
            onClose();
          } catch (err) {
            setError(err);
          } finally {
            setSaving(false);
          }
        }}
      >
        <Field label="Nova privremena lozinka" hint={PASSWORD_HINT + " Sve sesije korisnika biće odjavljene."}>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" />
        </Field>
        <ErrorText error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Otkaži
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            Postavi lozinku
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const [error, setError] = useState<unknown>(null);

  const reload = () => queryClient.invalidateQueries({ queryKey: ["users"] });
  const post = async (path: string) => {
    setError(null);
    try {
      await api(path, { method: "POST" });
      await reload();
    } catch (err) {
      setError(err);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Korisnici</h1>
        <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>
          Novi korisnik
        </Button>
      </div>
      <ErrorText error={error} />
      <Card>
        {users.isLoading ? (
          <Spinner />
        ) : (
          <Table head={["Korisnik", "Uloga", "Status", "Poslednja prijava", ""]}>
            {users.data?.map((u) => {
              const locked = u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <tr key={u.id}>
                  <Td>
                    <span className="font-medium">{u.username}</span>
                    {u.id === me?.id && <span className="text-xs text-slate-500"> (vi)</span>}
                    {u.email && <span className="block text-xs text-slate-500">{u.email}</span>}
                  </Td>
                  <Td>{ROLE_LABELS[u.role]}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {u.is_active ? <Badge tone="ok">Aktivan</Badge> : <Badge tone="unknown">Deaktiviran</Badge>}
                      {locked && <Badge tone="warning">Zaključan</Badge>}
                      {u.must_change_password && <Badge tone="info">Čeka promenu lozinke</Badge>}
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap">{formatDateTime(u.last_login_at)}</Td>
                  <Td>
                    <div className="flex flex-wrap justify-end gap-1">
                      <Button size="sm" onClick={() => setEditing(u)}>
                        Izmeni
                      </Button>
                      <Button size="sm" onClick={() => setResetting(u)}>
                        Reset lozinke
                      </Button>
                      {locked && (
                        <Button size="sm" onClick={() => post(`/users/${u.id}/unlock`)}>
                          Otključaj
                        </Button>
                      )}
                      {u.id !== me?.id && (
                        <Button size="sm" variant="ghost" onClick={() => confirm(`Odjaviti sve sesije korisnika ${u.username}?`) && post(`/users/${u.id}/logout-all`)}>
                          Odjavi sesije
                        </Button>
                      )}
                    </div>
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
      {editing && (
        <UserModal
          user={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      )}
      {resetting && (
        <ResetModal
          user={resetting}
          onClose={() => {
            setResetting(null);
            reload();
          }}
        />
      )}
    </div>
  );
}
