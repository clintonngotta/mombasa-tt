import { useState } from "react"
import { Link } from "react-router-dom"
import { RefreshCw } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { applyUpdate, useAppUpdate, type UpdateBlocker } from "@/lib/pwa"
import { cn } from "@/lib/utils"

/**
 * Offers the new version of the app once it has installed (REQ-035). The switch waits while a match is
 * open on the deck or score actions are still to be sent, and says so; nothing is reloaded by itself.
 */
export function UpdateBanner({ className }: { className?: string }) {
  const update = useAppUpdate()
  const [blocker, setBlocker] = useState<UpdateBlocker | null>(null)
  const [busy, setBusy] = useState(false)
  if (!update.waiting && !update.outdated && !update.switchedElsewhere) return null

  const apply = async () => {
    setBusy(true)
    try {
      setBlocker(await applyUpdate())
    } finally {
      setBusy(false)
    }
  }

  const title = update.outdated
    ? "This version of Coast TT is out of date"
    : update.switchedElsewhere
      ? "Coast TT was updated in another tab"
      : "A new version of Coast TT is ready"
  const body = update.outdated
    ? "Update to carry on. Scores waiting on this device stay here and are sent by the new version."
    : update.switchedElsewhere
      ? "Reload this page when you are ready to use it here."
      : "It takes a moment and keeps everything on this device."

  return (
    <div role="status" className={cn("flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-brand-blue/30 bg-surface-selected p-4 text-foreground", className)}>
      <RefreshCw aria-hidden className="size-5 shrink-0 text-brand-blue" />
      <div className="flex min-w-0 flex-1 flex-col">
        <p className="font-semibold">{title}</p>
        <p className="text-sm text-muted-foreground">{body}</p>
        {blocker && (
          <p className="mt-1 text-sm font-semibold">
            {blocker.scoring > 0
              ? "A match is open for scoring on this device. Finish or leave it, then update."
              : `${blocker.unsent} score ${blocker.unsent === 1 ? "action is" : "actions are"} still to be sent. Connect and wait for "Saved", then update.`}
          </p>
        )}
      </div>
      {blocker && blocker.scoring === 0 && blocker.unsent > 0 && (
        <Link to="/play" className={buttonVariants({ variant: "outline" })}>
          My matches
        </Link>
      )}
      <Button disabled={busy} onClick={() => void (update.switchedElsewhere ? window.location.reload() : apply())}>
        {update.switchedElsewhere ? "Reload" : busy ? "Checking…" : "Update now"}
      </Button>
    </div>
  )
}
