import { formatMoney } from "@/lib/coaching"
import type { PurposeTotal } from "@/lib/finance"
import { cn } from "@/lib/utils"

/** Received, spent and remaining per purpose; a deficit shows as a negative remainder. Dues still
 * expected are shown apart, never counted as received (REQ-024). */
export function PurposeTotals({ rows }: { rows: PurposeTotal[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((r) => (
        <li key={`${r.campaign_id ?? "general"}-${r.currency}`} className="flex flex-col gap-1 rounded-lg border bg-card px-4 py-3">
          <span className="font-semibold">{r.title}</span>
          <span className="text-sm">
            Received {formatMoney(r.received_minor, r.currency)} · spent {formatMoney(r.spent_minor, r.currency)} ·{" "}
            <span className={cn("font-semibold", r.remaining_minor < 0 && "text-destructive")}>
              {r.remaining_minor < 0 ? `deficit ${formatMoney(-r.remaining_minor, r.currency)}` : `${formatMoney(r.remaining_minor, r.currency)} left`}
            </span>
          </span>
          {r.expected_minor > 0 && <span className="text-sm text-muted-foreground">{formatMoney(r.expected_minor, r.currency)} in dues still to come in</span>}
        </li>
      ))}
    </ul>
  )
}
