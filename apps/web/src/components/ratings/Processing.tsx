import { Hourglass } from "lucide-react"

/** Shown while a result has not reached the ratings yet: what is on screen is provisional (REQ-016). */
export function Processing() {
  return (
    <p role="status" className="flex items-start gap-2 rounded-lg border bg-card p-3 text-sm">
      <Hourglass aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
      <span>
        <span className="font-semibold">Provisional.</span> A recent result is still being worked into the ratings. This updates by itself.
      </span>
    </p>
  )
}
