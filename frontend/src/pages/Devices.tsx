import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import DeviceForm from "../components/DeviceForm";
import { Badge, Button, Card, EmptyState, ErrorText, Spinner, Table, Td } from "../components/ui";
import { DEVICE_STATUS, formatDateTime, formatInterval, formatRelative } from "../format";
import type { Device, Disk } from "../types";

export default function DevicesPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api<Device[]>("/devices", { background: true }),
    refetchInterval: 15_000,
  });
  const canCollect = user?.role === "admin" || user?.role === "operator";
  const disks = useQuery({ queryKey: ["disks"], queryFn: () => api<Disk[]>("/disks", { background: true }), refetchInterval: 60_000 });
  const diskStats = (id: number) => {
    const own = (disks.data ?? []).filter((x) => x.device_id === id && x.is_present);
    return { total: own.length, warnings: own.filter((x) => x.state === "warning" || x.state === "critical").length };
  };

  const collect = async (device: Device) => {
    setActionError(null);
    try {
      await api(`/devices/${device.id}/collect`, { method: "POST" });
      await queryClient.invalidateQueries({ queryKey: ["devices"] });
    } catch (err) {
      setActionError(err);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Uređaji</h1>
        {user?.role === "admin" && (
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
            Dodaj uređaj
          </Button>
        )}
      </div>
      <ErrorText error={actionError} />
      <Card>
        {devices.isLoading ? (
          <Spinner />
        ) : devices.error ? (
          <ErrorText error={devices.error} />
        ) : devices.data!.length === 0 ? (
          <EmptyState>Nema dodatih uređaja.</EmptyState>
        ) : (
          <Table head={["Naziv", "Platforma", "Adresa", "Status", "Diskovi", "Interval", "Poslednje uspešno", "Sledeće", ""]}>
            {devices.data!.map((d) => {
              const status = DEVICE_STATUS[d.status];
              return (
                <tr key={d.id}>
                  <Td>
                    <Link to={`/uredjaji/${d.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-500">
                      {d.name}
                    </Link>
                    {d.location && <span className="block text-xs text-slate-500">{d.location}</span>}
                  </Td>
                  <Td>{d.platform_label}</Td>
                  <Td className="mono whitespace-nowrap">
                    {d.host}
                    {d.ssh_port !== 22 && `:${d.ssh_port}`}
                  </Td>
                  <Td>
                    <Badge tone={d.running ? "info" : status.tone}>{d.running ? "Prikupljanje u toku" : status.label}</Badge>
                    {d.status === "error" && d.last_error && <span className="mt-1 block max-w-xs text-xs text-red-700 dark:text-red-400">{d.last_error}</span>}
                  </Td>
                  <Td className="whitespace-nowrap">
                    {disks.data ? diskStats(d.id).total : "—"}
                    {diskStats(d.id).warnings > 0 && <span className="ml-1"><Badge tone="warning">{diskStats(d.id).warnings} upoz.</Badge></span>}
                  </Td>
                  <Td className="whitespace-nowrap">{formatInterval(d.effective_interval_minutes)}</Td>
                  <Td className="whitespace-nowrap" >
                    <span title={formatDateTime(d.last_success_at)}>{formatRelative(d.last_success_at)}</span>
                  </Td>
                  <Td className="whitespace-nowrap">
                    <span title={formatDateTime(d.next_run_at)}>{d.next_run_at ? formatRelative(d.next_run_at) : "—"}</span>
                  </Td>
                  <Td className="text-right">
                    {canCollect && d.status !== "not_configured" && (
                      <Button size="sm" icon={<RefreshCw className="size-3.5" />} disabled={d.running} onClick={() => collect(d)}>
                        Prikupi sada
                      </Button>
                    )}
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
      {adding && (
        <DeviceForm
          onClose={() => setAdding(false)}
          onSaved={(device) => {
            setAdding(false);
            queryClient.invalidateQueries({ queryKey: ["devices"] });
            navigate(`/uredjaji/${device.id}`);
          }}
        />
      )}
    </div>
  );
}
