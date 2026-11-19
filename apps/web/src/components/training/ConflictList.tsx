import { TriangleAlert } from "lucide-react"
import { formatInstant } from "@/lib/dates"
import type { CalendarConflict } from "@/lib/training"

const KIND: Record<CalendarConflict["kind"], string> = {
  training: "Training",
  match: "Match",
  booking: "Coaching",
  club_session: "Club session",
  tournament: "Tournament",
}

/** What stands in the way of a time: shown before anything is confirmed (REQ-027). */
export function ConflictList({ conflicts, timeZone, lead, next }: { conflicts: CalendarConflict[]; timeZone: string; lead: string; next: string }) {
  if (!conflicts.length) return null
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-xl border border-warning/40 bg-warning/10 p-4">
      <p className="flex items-center gap-2 font-semibold">
        <TriangleAlert aria-hidden className="size-5 text-warning" /> {lead}
      </p>
      <ul className="flex list-disc flex-col gap-1 pl-6">
        {conflicts.map((c) => (
          <li key={`${c.kind}-${c.title}-${c.starts_at}`}>
            {KIND[c.kind] ?? "Booked"}: {c.title}
            {c.tables?.length ? ` (${c.tables.join(", ")})` : ""}, {formatInstant(c.starts_at, timeZone)} to {formatInstant(c.ends_at, timeZone)}
          </li>
        ))}
      </ul>
      <p>{next}</p>
    </div>
  )
}
