import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { cancelAdminNomination, clubKeys, getOrganizationAdmin, type AdminHandover, type Membership } from "@/lib/clubs"

const STATUS: Record<AdminHandover["status"], string> = {
  pending: "waiting for an answer",
  accepted: "accepted",
  declined: "declined",
  cancelled: "cancelled",
}

/** Who the organization's one admin is (REQ-045), the open nomination and, for role managers, the history. */
export function AdminPanel({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const timeZone = membership.organization.timezone
  const queryClient = useQueryClient()
  const admin = useQuery({ queryKey: clubKeys.admin(orgId), queryFn: () => getOrganizationAdmin(orgId) })
  const cancel = useMutation({
    mutationFn: () => cancelAdminNomination(orgId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.admin(orgId) }),
  })
  const iAmAdmin = membership.roles.some((role) => role.key === "admin")
  if (admin.isPending) return null
  if (admin.isError) return <FormAlert>{errorMessage(admin.error, "We couldn't load who the admin is.")}</FormAlert>
  const { pending, history } = admin.data

  return (
    <section aria-labelledby="admin-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="admin-heading" className="flex items-center gap-2 text-lg font-bold">
        <ShieldCheck aria-hidden className="size-5 text-brand-blue" /> Club admin
      </h2>
      <p>
        <span className="font-semibold">{admin.data.admin?.display_name ?? "No admin"}</span>
        {iAmAdmin && <span className="text-muted-foreground"> (you)</span>}
      </p>
      <p className="text-sm text-muted-foreground">
        The admin has full control of the club and gives others what they need through roles. The admin changes only when they nominate a member and that member
        accepts.
        {iAmAdmin && !pending && " To hand over, choose Make admin on a member below."}
      </p>
      {pending && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-sm">
            {pending.to_user.display_name} is nominated to take over, {STATUS.pending}.
          </p>
          {iAmAdmin && (
            <Button variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              {cancel.isPending ? "Cancelling…" : "Cancel nomination"}
            </Button>
          )}
        </div>
      )}
      {cancel.isError && <FormAlert>{errorMessage(cancel.error)}</FormAlert>}
      {history && history.length > 0 && (
        <details>
          <summary className="min-h-11 cursor-pointer content-center text-sm font-semibold">Past handovers</summary>
          <ul className="flex flex-col gap-1 text-sm">
            {history.map((item) => (
              <li key={item.id}>
                {formatInstant(item.decided_at ?? item.created_at, timeZone)}: {item.from_user?.display_name ?? "No admin"} → {item.to_user.display_name},{" "}
                {item.kind === "appointment" ? `appointed by the platform${item.reason ? ` (${item.reason})` : ""}` : STATUS[item.status]}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
