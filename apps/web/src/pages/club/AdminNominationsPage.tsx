import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { answerAdminNomination, clubKeys, listMyAdminNominations, setActiveOrganization } from "@/lib/clubs"

/** Nominations naming the player as an organization's next admin (REQ-045). Nothing changes until they accept. */
export function AdminNominationsPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const nominations = useQuery({ queryKey: clubKeys.myAdminNominations, queryFn: listMyAdminNominations })
  const answer = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) => answerAdminNomination(id, accept),
    onSuccess: (handover, { accept }) => {
      if (accept) {
        setActiveOrganization(handover.organization.id)
        navigate("/club/members")
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.all }),
  })
  const items = nominations.data?.results ?? []

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Admin nominations</h1>
      {nominations.isPending && <p className="text-muted-foreground">Loading…</p>}
      {nominations.isError && <FormAlert>{errorMessage(nominations.error, "We couldn't load your nominations.")}</FormAlert>}
      {answer.isError && <FormAlert>{errorMessage(answer.error)}</FormAlert>}
      {nominations.isSuccess && items.length === 0 && <p className="text-muted-foreground">No open nominations.</p>}
      <ul className="flex flex-col gap-3">
        {items.map((nomination) => {
          const busy = answer.isPending && answer.variables?.id === nomination.id
          const club = nomination.organization.name
          return (
            <li key={nomination.id} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
              <p className="font-semibold">{club}</p>
              <p className="text-sm text-muted-foreground">
                {nomination.from_user?.display_name ?? "The admin"} nominated you to take over as admin. The admin has full control of the club: settings, roles,
                committee and nominations. The current admin keeps only their other roles.
              </p>
              <div className="flex gap-2">
                <Button disabled={busy} aria-label={`Become the admin of ${club}`} onClick={() => answer.mutate({ id: nomination.id, accept: true })}>
                  Accept
                </Button>
                <Button variant="outline" disabled={busy} aria-label={`Decline the admin nomination for ${club}`} onClick={() => answer.mutate({ id: nomination.id, accept: false })}>
                  Decline
                </Button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
