import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { formatDateTime } from "../format";
import { Alert, Badge, Button, Card, CopyButton, ErrorText, Field, Input, Select, Table, Td } from "./ui";

type Token = { id: number; name: string; prefix: string; scope: "read" | "operator"; created_at: string; expires_at: string | null; revoked_at: string | null; last_used_at: string | null; last_used_ip: string | null; state: "active" | "expired" | "revoked"; owner: string | null };

/** API tokeni (spec. §16.7): ograničena dozvola, rok važenja, opoziv; token se prikazuje samo jednom. */
export default function TokensCard() {
  const queryClient = useQueryClient();
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: () => api<Token[]>("/tokens") });
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "operator">("read");
  const [days, setDays] = useState("90");
  const [created, setCreated] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ token: string }>("/tokens", { method: "POST", body: { name, scope, expires_days: days ? Number(days) : null } });
      setCreated(r.token);
      setName("");
      await queryClient.invalidateQueries({ queryKey: ["tokens"] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (id: number) => {
    await api(`/tokens/${id}/revoke`, { method: "POST" });
    await queryClient.invalidateQueries({ queryKey: ["tokens"] });
  };

  return (
    <Card title={<span className="inline-flex items-center gap-2"><KeyRound className="size-4" /> API tokeni</span>}>
      <div className="space-y-3 text-sm">
        <p className="text-slate-500">
          Za skripte i druge sisteme: zaglavlje <code>Authorization: Bearer sdk_…</code>. „Čitanje” dozvoljava samo GET zahteve; „Operater” i ručno prikupljanje i potvrdu alarma.
          Token nikad nema administratorska prava. Dokumentacija API-ja: <a className="text-brand-700 hover:underline dark:text-brand-500" href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a>.
        </p>
        {created && (
          <Alert tone="warning" title="Sačuvajte token sada – kasnije se ne može ponovo prikazati">
            <div className="mt-1 flex flex-wrap items-center gap-2"><code className="break-all">{created}</code><CopyButton text={created} /></div>
          </Alert>
        )}
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Naziv"><Input className="max-w-56" value={name} onChange={(e) => setName(e.target.value)} placeholder="npr. Grafana" /></Field>
          <Field label="Dozvola"><Select value={scope} onChange={(e) => setScope(e.target.value as "read" | "operator")}><option value="read">Čitanje</option><option value="operator">Operater</option></Select></Field>
          <Field label="Važi (dana)"><Select value={days} onChange={(e) => setDays(e.target.value)}><option value="30">30</option><option value="90">90</option><option value="365">365</option><option value="">bez isteka</option></Select></Field>
          <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={create}>Napravi token</Button>
        </div>
        <ErrorText error={error} />
        {(tokens.data ?? []).length > 0 && (
          <Table head={["Naziv", "Token", "Dozvola", "Vlasnik", "Ističe", "Poslednja upotreba", "Stanje", ""]}>
            {tokens.data!.map((t) => (
              <tr key={t.id}>
                <Td>{t.name}</Td>
                <Td className="mono text-xs">{t.prefix}…</Td>
                <Td>{t.scope === "read" ? "Čitanje" : "Operater"}</Td>
                <Td>{t.owner}</Td>
                <Td className="whitespace-nowrap">{t.expires_at ? formatDateTime(t.expires_at) : "bez isteka"}</Td>
                <Td className="whitespace-nowrap text-xs">{formatDateTime(t.last_used_at)} {t.last_used_ip}</Td>
                <Td><Badge tone={t.state === "active" ? "ok" : "unknown"}>{t.state === "active" ? "Aktivan" : t.state === "expired" ? "Istekao" : "Opozvan"}</Badge></Td>
                <Td>{t.state === "active" && <Button size="sm" variant="ghost" onClick={() => revoke(t.id)}>Opozovi</Button>}</Td>
              </tr>
            ))}
          </Table>
        )}
      </div>
    </Card>
  );
}
