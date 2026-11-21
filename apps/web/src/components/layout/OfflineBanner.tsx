import { Link } from "react-router-dom"
import { CloudOff, RefreshCw, TriangleAlert } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"
import { useSyncState } from "@/lib/offline"
import { cn } from "@/lib/utils"

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`

function savedWhen(iso: string) {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })
}

/**
 * Says when the app is working from the device (REQ-035). It shows when there is no connection, when
 * changes are waiting to be sent, or when some were refused or can't be sent until the person logs in
 * again. Otherwise nothing is shown.
 */
export function OfflineBanner({ className }: { className?: string }) {
  const sync = useSyncState()
  const problem = sync.refused > 0 || sync.signedOut
  if (sync.online && sync.waiting === 0 && !problem) return null

  const Icon = problem ? TriangleAlert : sync.online ? RefreshCw : CloudOff
  const title = !sync.online
    ? "You're offline"
    : sync.signedOut
      ? "Log in again to send your changes"
      : sync.refused > 0
        ? `${plural(sync.refused, "change wasn't", "changes weren't")} accepted`
        : sync.syncing
          ? "Sending your changes…"
          : `${plural(sync.waiting, "change", "changes")} waiting to be sent`
  const parts: string[] = []
  if (!sync.online) parts.push(sync.savedAt ? `Showing what this device saved on ${savedWhen(sync.savedAt)}.` : "Screens you have opened before still show what was saved on this device.")
  if (sync.waiting > 0) parts.push(`${plural(sync.waiting, "change is", "changes are")} kept on this device and will be sent when you're back online.`)
  else if (!sync.online) parts.push("Changes you can make offline are kept here and sent when you're back online.")
  if (sync.signedOut) parts.push("Your session ended. Log in as the same person and they will be sent.")
  if (sync.refused > 0) parts.push("Look at them and decide whether to try again or discard them.")

  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border p-4 text-foreground",
        problem ? "border-warning/40 bg-warning/5" : "border-border bg-muted/50",
        className
      )}
    >
      <Icon aria-hidden className={cn("size-5 shrink-0", problem ? "text-warning" : "text-muted-foreground", sync.syncing && "animate-spin")} />
      <div className="flex min-w-0 flex-1 flex-col">
        <p className="font-semibold">{title}</p>
        <p className="text-sm text-muted-foreground">{parts.join(" ")}</p>
      </div>
      {sync.signedOut ? (
        <Link to={`/login?next=${encodeURIComponent("/profile/sync")}`} className={buttonVariants()}>
          Log in
        </Link>
      ) : (
        (sync.waiting > 0 || sync.refused > 0) && (
          <Link to="/profile/sync" className={buttonVariants({ variant: "outline" })}>
            See changes
          </Link>
        )
      )}
    </div>
  )
}
