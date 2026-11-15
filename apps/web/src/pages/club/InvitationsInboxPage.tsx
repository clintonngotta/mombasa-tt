import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { OrganizationCard } from "@/components/clubs/OrganizationCard"
import { errorMessage } from "@/lib/api"
import { acceptInvitation, clubKeys, declineInvitation, listMyInvitations, setActiveOrganization } from "@/lib/clubs"
import { useMe } from "@/lib/session"

/** Invitations addressed to the player's verified email (REQ-004: members explicitly accept). */
export function InvitationsInboxPage() {
  const me = useMe()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const invitations = useQuery({ queryKey: clubKeys.myInvitations, queryFn: listMyInvitations })

  const answer = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) => (accept ? acceptInvitation(id) : declineInvitation(id)),
    onSuccess: async (invitation, { accept }) => {
      await queryClient.invalidateQueries({ queryKey: ["clubs"] })
      if (accept) {
        setActiveOrganization(invitation.organization.id)
        navigate("/club")
      }
    },
  })
  const items = invitations.data?.results ?? []

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <Link to="/club" className="flex items-center gap-1 self-start text-sm font-semibold text-muted-foreground hover:text-foreground">
        <ArrowLeft aria-hidden className="size-4" /> Club
      </Link>
      <h1 className="text-[32px] leading-9 font-bold">Invitations</h1>

      {me.data && !me.data.email_verified_at && (
        <FormAlert>Verify your email address to see invitations sent to it.</FormAlert>
      )}
      {invitations.isPending && <p className="text-muted-foreground">Loading invitations…</p>}
      {invitations.isError && <FormAlert>{errorMessage(invitations.error, "We couldn't load your invitations.")}</FormAlert>}
      {answer.isError && <FormAlert>{errorMessage(answer.error, "That invitation is no longer open.")}</FormAlert>}
      {invitations.isSuccess && items.length === 0 && (
        <p className="text-muted-foreground">No open invitations. Invitations that were revoked, answered or expired don't appear here.</p>
      )}

      <ul className="flex flex-col gap-3">
        {items.map((invitation) => {
          const busy = answer.isPending && answer.variables?.id === invitation.id
          return (
            <li key={invitation.id} className="flex flex-col gap-3">
              <OrganizationCard organization={invitation.organization} />
              <p className="text-sm text-muted-foreground">
                {invitation.invited_by_name ? `${invitation.invited_by_name} invited you` : "You're invited"} to join as a member.
              </p>
              <div className="flex gap-2">
                <Button disabled={busy} onClick={() => answer.mutate({ id: invitation.id, accept: true })}>
                  Accept
                </Button>
                <Button variant="outline" disabled={busy} onClick={() => answer.mutate({ id: invitation.id, accept: false })}>
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
