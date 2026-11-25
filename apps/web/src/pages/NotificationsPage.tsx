import { useState } from "react"
import { AddEmailPrompt } from "@/components/profile/AddEmailPrompt"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { PushSettings } from "@/components/notifications/PushSettings"
import { errorMessage } from "@/lib/api"
import { alertKeys, getPreferences, listAlerts, markAllRead, markRead, savePreferences, type Alert } from "@/lib/notifications"
import { cn } from "@/lib/utils"

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })

/** The inbox (REQ-019): every alert stays here, read or not, whether or not push is on. Opening one
 * shows its subject as it is now; an alert a newer one replaced says so. */
export function NotificationsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const alerts = useQuery({ queryKey: alertKeys.list(unreadOnly), queryFn: () => listAlerts(unreadOnly) })
  const refresh = () => queryClient.invalidateQueries({ queryKey: alertKeys.all })
  const open = useMutation({
    mutationFn: (alert: Alert) => markRead(alert.id),
    onSuccess: (alert) => {
      void refresh()
      if (alert.link) navigate(alert.link)
    },
  })
  const all = useMutation({ mutationFn: markAllRead, onSuccess: () => void refresh() })
  const list = alerts.data?.results ?? []

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <h1 className="text-[32px] leading-9 font-bold">Notifications</h1>
      <AddEmailPrompt />
      <div className="flex flex-wrap items-center gap-2">
        <Button variant={unreadOnly ? "default" : "outline"} aria-pressed={unreadOnly} onClick={() => setUnreadOnly(!unreadOnly)}>
          Unread only
        </Button>
        <Button variant="ghost" disabled={all.isPending} onClick={() => all.mutate()}>
          Mark all read
        </Button>
      </div>
      {alerts.isError && <FormAlert>{errorMessage(alerts.error, "We couldn't load your notifications.")}</FormAlert>}
      {alerts.isSuccess && list.length === 0 && <p className="text-muted-foreground">Nothing here.</p>}
      <ul className="flex flex-col gap-2">
        {list.map((alert) => (
          <li key={alert.id}>
            <button
              type="button"
              onClick={() => open.mutate(alert)}
              className={cn("flex w-full flex-col items-start gap-0.5 rounded-xl border bg-card p-4 text-left outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50", !alert.read && "border-brand-blue")}
            >
              <span className={cn("font-semibold", alert.superseded && "text-muted-foreground line-through")}>{alert.title}</span>
              {alert.body && <span className="text-sm">{alert.body}</span>}
              <span className="text-sm text-muted-foreground">
                {when(alert.created_at)}
                {alert.superseded && " · out of date: open it to see where things stand now"}
                {!alert.read && " · new"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <Preferences />
      <PushSettings />
    </div>
  )
}

function Preferences() {
  const queryClient = useQueryClient()
  const prefs = useQuery({ queryKey: alertKeys.preferences, queryFn: getPreferences })
  const save = useMutation({
    mutationFn: (row: { category: string; enabled: boolean }) => savePreferences([row as never]),
    onSuccess: (fresh) => queryClient.setQueryData(alertKeys.preferences, fresh),
  })
  return (
    <section aria-labelledby="prefs-heading" className="flex flex-col gap-2 border-t pt-6">
      <h2 id="prefs-heading" className="text-xl font-bold">
        What you get
      </h2>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <ul className="flex flex-col gap-1">
        {(prefs.data?.preferences ?? []).map((p) => (
          <li key={p.category}>
            <label className="flex min-h-12 items-center gap-3">
              <input type="checkbox" className="size-5 accent-brand-blue" checked={p.enabled} disabled={p.locked || save.isPending} onChange={(e) => save.mutate({ category: p.category, enabled: e.target.checked })} />
              <span>
                {p.label}
                {p.locked && <span className="text-sm text-muted-foreground"> · always on</span>}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </section>
  )
}
