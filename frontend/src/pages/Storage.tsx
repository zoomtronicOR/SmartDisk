import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { PoolCard } from "../components/storage";
import { EmptyState, ErrorText, Spinner } from "../components/ui";
import type { Pool } from "../types";

export default function StoragePage() {
  const pools = useQuery({
    queryKey: ["pools"],
    queryFn: () => api<Pool[]>("/pools", { background: true }),
    refetchInterval: 30_000,
  });
  if (pools.isLoading) return <Spinner />;
  if (pools.error) return <ErrorText error={pools.error} />;

  const groups = new Map<number, { name: string; pools: Pool[] }>();
  for (const pool of pools.data ?? []) {
    const group = groups.get(pool.device_id) ?? { name: pool.device_name, pools: [] };
    group.pools.push(pool);
    groups.set(pool.device_id, group);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Skladište</h1>
      {groups.size === 0 && <EmptyState>Još nema podataka o skladištu. Pojavljuju se posle prvog uspešnog prikupljanja.</EmptyState>}
      {[...groups.entries()].map(([deviceId, group]) => (
        <section key={deviceId} className="space-y-3">
          <h2 className="text-lg font-semibold">
            <Link to={`/uredjaji/${deviceId}`} className="hover:underline">{group.name}</Link>
          </h2>
          <div className="grid gap-4 xl:grid-cols-2">
            {group.pools.map((pool) => (
              <PoolCard key={pool.id} pool={pool} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
