import { Check, Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { JoinState } from "@/lib/clubs"

export function JoinStatus({ state, name, busy, onJoin }: { state: JoinState; name: string; busy: boolean; onJoin: () => void }) {
  if (state === "member") {
    return (
      <span className="flex items-center gap-1 text-sm font-semibold text-success">
        <Check aria-hidden className="size-4" /> Member
      </span>
    )
  }
  if (state === "pending") {
    return (
      <span className="flex items-center gap-1 text-sm font-semibold text-warning">
        <Clock aria-hidden className="size-4" /> Request pending
      </span>
    )
  }
  if (state === "unknown") return null
  return (
    <Button variant="outline" aria-label={`Request to join ${name}`} disabled={busy} onClick={onJoin}>
      {busy ? "Sending…" : "Request to join"}
    </Button>
  )
}
