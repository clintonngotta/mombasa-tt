import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { CloudOff, RefreshCw, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { discardChange, pendingChanges, retryChange, syncNow, useSyncState, type PendingChange } from "@/lib/offline"

const KEY = ["offline", "changes"] as const

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })
}

/**
 * Changes kept on this device (REQ-035): the ones waiting to be sent, and the ones the server didn't
 * accept, with its reason. A refused change stays until the person tries it again or discards it.
 */
export function SyncPage() {
  const sync = useSyncState()
  const queryClient = useQueryClient()
  // The list lives on the device, not the server: read it again whenever the counts move.
  const changes = useQuery({ queryKey: [...KEY, sync.waiting, sync.refused, sync.syncing], queryFn: pendingChanges, networkMode: "always", gcTime: 0 })
  const [busy, setBusy] = useState<string | null>(null)
  const act = async (id: string, work: (id: string) => Promise<void>) => {
    setBusy(id)
    try {
      await work(id)
    } finally {
      setBusy(null)
      void queryClient.invalidateQueries({ queryKey: KEY })
    }
  }
  const list = changes.data ?? []
  const refused = list.filter((change) => change.state === "refused")
  const waiting = list.filter((change) => change.state === "waiting")

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Waiting to sync</h1>
        <p className="text-muted-foreground">Changes you made without a connection are kept on this device and sent, in order, when you're back online.</p>
      </div>

      {list.length === 0 && !changes.isPending && <p className="rounded-xl border bg-card p-4 text-muted-foreground">Everything on this device has been sent.</p>}

      {refused.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-xl font-bold">Not accepted</h2>
          <p className="text-sm text-muted-foreground">Coast TT didn't take these, usually because something changed while you were offline. Try again or discard them.</p>
          {refused.map((change) => (
            <ChangeRow key={change.id} change={change}>
              <p className="text-sm font-semibold text-warning">{change.message}</p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={busy === change.id || !sync.online} onClick={() => void act(change.id, retryChange)}>
                  <RefreshCw aria-hidden /> Try again
                </Button>
                <Button size="sm" variant="ghost" disabled={busy === change.id} onClick={() => void act(change.id, discardChange)}>
                  <Trash2 aria-hidden /> Discard
                </Button>
              </div>
            </ChangeRow>
          ))}
        </section>
      )}

      {waiting.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-xl font-bold">Waiting to be sent</h2>
          {!sync.online && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <CloudOff aria-hidden className="size-4" /> You're offline. They will be sent when the connection is back.
            </p>
          )}
          {waiting.map((change) => (
            <ChangeRow key={change.id} change={change} />
          ))}
          <Button className="self-start" disabled={!sync.online || sync.syncing} onClick={() => void syncNow()}>
            {sync.syncing ? "Sending…" : "Send now"}
          </Button>
        </section>
      )}
    </div>
  )
}

function ChangeRow({ change, children }: { change: PendingChange; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-semibold">{change.label}</p>
        <p className="text-sm text-muted-foreground">{when(change.createdAt)}</p>
      </div>
      {children}
    </div>
  )
}
