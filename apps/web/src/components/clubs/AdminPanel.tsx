import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { cancelAdminNomination, clubKeys, getOrganizationAdmin, stepDownAsAdmin, type AdminHandover, type Membership } from "@/lib/clubs"
import { useMe } from "@/lib/session"

const STATUS: Record<AdminHandover["status"], string> = {
  pending: "waiting for an answer",
  accepted: "accepted",
  declined: "declined",
  cancelled: "cancelled",
}

/** One line of the history: who it concerned and what happened. */
function pastChange(item: AdminHandover) {
  const from = item.from_user?.display_name ?? "No admin"
  const to = item.to_user.display_name
  if (item.kind === "step_down") return `${to} stepped down as admin`
  if (item.kind === "appointment") {
    const reason = item.reason ? ` (${item.reason})` : ""
    return `${to} appointed by the platform${item.from_user ? `, replacing ${from}` : ""}${reason}`
  }
  if (item.kind === "addition") return `${from} nominated ${to} as a further admin, ${STATUS[item.status]}`
  return `${from} → ${to}, ${STATUS[item.status]}`
}

/** Who the organization's admins are (up to three, REQ-045), the open nominations and, for role managers, the history. */
export function AdminPanel({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const timeZone = membership.organization.timezone
  const queryClient = useQueryClient()
  const user = useMe().data
  const [confirmStepDown, setConfirmStepDown] = useState(false)
  const admin = useQuery({ queryKey: clubKeys.admin(orgId), queryFn: () => getOrganizationAdmin(orgId) })
  const cancel = useMutation({
    mutationFn: (handoverId: string) => cancelAdminNomination(orgId, handoverId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.admin(orgId) }),
  })
  const stepDown = useMutation({
    mutationFn: () => stepDownAsAdmin(orgId),
    onSuccess: () => setConfirmStepDown(false),
    // The roles in the cached membership list decide what this player may still open.
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.all }),
  })
  const iAmAdmin = membership.roles.some((role) => role.key === "admin")
  if (admin.isPending) return null
  if (admin.isError) return <FormAlert>{errorMessage(admin.error, "We couldn't load who the admins are.")}</FormAlert>
  const { admins, nominations, history, limit } = admin.data
  const offered = nominations.filter((nomination) => nomination.kind === "addition").length
  const free = Math.max(0, limit - admins.length - offered)

  return (
    <section aria-labelledby="admin-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="admin-heading" className="flex items-center gap-2 text-lg font-bold">
        <ShieldCheck aria-hidden className="size-5 text-brand-blue" /> Club admins
        <span className="text-sm font-semibold text-muted-foreground">
          {admins.length} of {limit}
        </span>
      </h2>
      {admins.length === 0 ? (
        <p className="font-semibold">No admin</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {admins.map((person) => (
            <li key={person.id}>
              <span className="font-semibold">{person.display_name}</span>
              {person.id === user?.id && <span className="text-muted-foreground"> (you)</span>}
            </li>
          ))}
        </ul>
      )}
      <p className="text-sm text-muted-foreground">
        An admin has full control of the club and gives others what they need through roles. A club has up to {limit} admins. A member becomes one only when an
        admin nominates them and they accept.
        {iAmAdmin && (free > 0 ? " To add one or hand over your place, choose Make admin on a member below." : " Every place is taken or offered. You can still hand over your own place: choose Make admin on a member below.")}
      </p>
      {nominations.map((nomination) => {
        const mine = nomination.from_user?.id === user?.id
        const busy = cancel.isPending && cancel.variables === nomination.id
        return (
          <div key={nomination.id} className="flex flex-wrap items-center gap-2">
            <p className="flex-1 text-sm">
              {nomination.kind === "addition"
                ? `${nomination.to_user.display_name} is nominated as a further admin, ${STATUS.pending}.`
                : `${nomination.to_user.display_name} is nominated to take over from ${mine ? "you" : (nomination.from_user?.display_name ?? "an admin")}, ${STATUS.pending}.`}
            </p>
            {/* Any admin withdraws an offer of a further place; a successor only whoever chose them. */}
            {iAmAdmin && (nomination.kind === "addition" || mine) && (
              <Button variant="outline" disabled={busy} aria-label={`Cancel the nomination of ${nomination.to_user.display_name}`} onClick={() => cancel.mutate(nomination.id)}>
                {busy ? "Cancelling…" : "Cancel nomination"}
              </Button>
            )}
          </div>
        )
      })}
      {cancel.isError && <FormAlert>{errorMessage(cancel.error)}</FormAlert>}
      {iAmAdmin && admins.length > 1 && !confirmStepDown && (
        <Button variant="outline" className="self-start" onClick={() => setConfirmStepDown(true)}>
          Step down as admin
        </Button>
      )}
      {confirmStepDown && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-sm">Step down as admin? You stay a member and keep your other roles. To be an admin again, an admin must nominate you.</p>
          <Button variant="outline" onClick={() => setConfirmStepDown(false)}>
            Stay
          </Button>
          <Button variant="destructive" disabled={stepDown.isPending} onClick={() => stepDown.mutate()}>
            {stepDown.isPending ? "Stepping down…" : "Step down"}
          </Button>
        </div>
      )}
      {stepDown.isError && <FormAlert>{errorMessage(stepDown.error)}</FormAlert>}
      {history && history.length > 0 && (
        <details>
          <summary className="min-h-11 cursor-pointer content-center text-sm font-semibold">Past changes</summary>
          <ul className="flex flex-col gap-1 text-sm">
            {history.map((item) => (
              <li key={item.id}>
                {formatInstant(item.decided_at ?? item.created_at, timeZone)}: {pastChange(item)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
