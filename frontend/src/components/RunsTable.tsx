import { Link } from "react-router-dom";
import { formatDateTime, formatDuration, RUN_STATUS, RUN_TRIGGER } from "../format";
import type { Run } from "../types";
import { Badge, EmptyState, Table, Td } from "./ui";

export default function RunsTable({ runs, showDevice }: { runs: Run[]; showDevice?: boolean }) {
  if (runs.length === 0) return <EmptyState>Još nema prikupljanja.</EmptyState>;
  return (
    <Table head={[...(showDevice ? ["Uređaj"] : []), "Početak", "Vrsta", "Status", "Trajanje", "Detalji"]}>
      {runs.map((run) => {
        const status = RUN_STATUS[run.status];
        const warnings = run.details?.warnings ?? [];
        return (
          <tr key={run.id}>
            {showDevice && (
              <Td>
                <Link className="font-medium text-brand-700 hover:underline dark:text-brand-500" to={`/uredjaji/${run.device_id}`}>
                  {run.device_name}
                </Link>
              </Td>
            )}
            <Td className="whitespace-nowrap">{formatDateTime(run.started_at)}</Td>
            <Td>
              {RUN_TRIGGER[run.trigger]}
              {run.initiated_by && <span className="block text-xs text-slate-500">{run.initiated_by}</span>}
            </Td>
            <Td>
              <Badge tone={status.tone}>{status.label}</Badge>
            </Td>
            <Td className="whitespace-nowrap">{formatDuration(run.duration_ms)}</Td>
            <Td className="max-w-md">
              {run.status === "failed" && run.error_message && <p className="text-red-700 dark:text-red-400">{run.error_message}</p>}
              {run.status === "partial" && (run.details?.errors ?? []).length > 0 && (
                <ul className="list-disc pl-4 text-xs text-red-700 dark:text-red-400">
                  {run.details!.errors!.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              )}
              {run.details?.os_info && <p>{run.details.os_info}</p>}
              {run.disks_found != null && (
                <p className="text-xs text-slate-500">
                  Diskova: {run.disks_found}
                  {run.details?.pools_found != null && ` · skladišta: ${run.details.pools_found}`}
                  {run.errors_count > 0 && ` · grešaka: ${run.errors_count}`}
                </p>
              )}
              {warnings.length > 0 && (
                <ul className="mt-1 list-disc pl-4 text-xs text-amber-700 dark:text-amber-400">
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
            </Td>
          </tr>
        );
      })}
    </Table>
  );
}
