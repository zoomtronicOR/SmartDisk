import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Button, Card, ErrorText, Select, Spinner, Table, Td } from "../components/ui";
import { formatDateTime } from "../format";
import type { AuditEntry } from "../types";

const PAGE = 50;

const ACTION_LABELS: Record<string, string> = {
  "login.success": "Prijava",
  "login.failure": "Neuspešna prijava",
  "login.locked": "Prijava na zaključan nalog",
  logout: "Odjava",
  "user.created": "Kreiran korisnik",
  "user.updated": "Izmenjen korisnik",
  "user.password_reset": "Reset lozinke",
  "user.password_changed": "Promena lozinke",
  "user.unlocked": "Otključan nalog",
  "user.auto_locked": "Automatsko zaključavanje",
  "user.sessions_revoked": "Odjavljene sesije",
  "device.created": "Dodat uređaj",
  "device.updated": "Izmenjen uređaj",
  "device.deleted": "Obrisan uređaj",
  "device.credentials_set": "Postavljen SSH ključ",
  "device.host_key_fetched": "Preuzet host ključ",
  "device.host_key_confirmed": "Potvrđen host ključ",
  "device.host_key_changed": "Promenjen host ključ",
  "device.test_connection": "Test konekcije",
  "device.collect_manual": "Ručno prikupljanje",
  "settings.collection_updated": "Promena intervala",
  "settings.general_updated": "Promena opštih podešavanja",
};

export default function AuditPage() {
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const query = useQuery({
    queryKey: ["audit", offset, action],
    queryFn: () => api<{ items: AuditEntry[]; total: number }>(`/audit?limit=${PAGE}&offset=${offset}${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Audit log</h1>
      <Card
        actions={
          <Select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setOffset(0);
            }}
            className="w-56"
          >
            <option value="">Sve radnje</option>
            <option value="login">Prijave</option>
            <option value="user.">Korisnici</option>
            <option value="device.">Uređaji</option>
            <option value="settings.">Podešavanja</option>
          </Select>
        }
      >
        {query.isLoading ? (
          <Spinner />
        ) : query.error ? (
          <ErrorText error={query.error} />
        ) : (
          <>
            <Table head={["Vreme", "Korisnik", "Radnja", "Objekat", "IP", "Detalji"]}>
              {query.data!.items.map((e) => (
                <tr key={e.id}>
                  <Td className="whitespace-nowrap">{formatDateTime(e.created_at)}</Td>
                  <Td>{e.username ?? "—"}</Td>
                  <Td>
                    {ACTION_LABELS[e.action] ?? e.action}
                    <code className="block text-xs text-slate-400">{e.action}</code>
                  </Td>
                  <Td>{e.entity_type ? `${e.entity_type} #${e.entity_id}` : "—"}</Td>
                  <Td className="mono text-xs">{e.source_ip ?? "—"}</Td>
                  <Td className="mono max-w-sm break-all text-xs">{e.details ? JSON.stringify(e.details) : ""}</Td>
                </tr>
              ))}
            </Table>
            <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
              <span>
                {query.data!.total === 0 ? "Nema zapisa" : `${offset + 1}–${Math.min(offset + PAGE, query.data!.total)} od ${query.data!.total}`}
              </span>
              <div className="flex gap-2">
                <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                  Prethodna
                </Button>
                <Button size="sm" disabled={offset + PAGE >= query.data!.total} onClick={() => setOffset(offset + PAGE)}>
                  Sledeća
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
