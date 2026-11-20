import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { acceptGuestInvitation, declineGuestInvitation, guestKeys, listMyClaims, listMyGuestInvitations } from "@/lib/guests"
import { useMe } from "@/lib/session"

/**
 * A club entered you as a guest before you had an account (REQ-003): accept, and that guest's entries
 * and matches become yours. Only invitations to your verified address appear, and each works once.
 */
export function GuestClaimsPage() {
  const me = useMe()
  const queryClient = useQueryClient()
  const invitations = useQuery({ queryKey: guestKeys.myInvitations, queryFn: listMyGuestInvitations })
  const claims = useQuery({ queryKey: guestKeys.myClaims, queryFn: listMyClaims })
  const answer = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) => (accept ? acceptGuestInvitation(id).then(() => undefined) : declineGuestInvitation(id)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: guestKeys.all }),
  })
  const answerError =
    answer.error instanceof ApiError && answer.error.status === 404 ? "That invitation is no longer open. It may have been withdrawn or expired." : errorMessage(answer.error)
  const open = invitations.data?.results ?? []
  const past = claims.data?.results ?? []

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/profile">Profile</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Matches entered for you</h1>
      {me.data && !me.data.email_verified_at && <FormAlert>Verify your email address to see invitations sent to it.</FormAlert>}
      {invitations.isError && <FormAlert>{errorMessage(invitations.error, "We couldn't load your invitations.")}</FormAlert>}
      {answer.isError && <FormAlert>{answerError}</FormAlert>}
      {invitations.isSuccess && open.length === 0 && <p className="text-muted-foreground">No open invitations to claim a guest.</p>}

      <ul className="flex flex-col gap-3">
        {open.map((invitation) => {
          const busy = answer.isPending && answer.variables?.id === invitation.id
          return (
            <li key={invitation.id} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
              <p>
                {invitation.invited_by_name ?? "Club staff"} at <span className="font-semibold">{invitation.organization_name}</span> entered you as{" "}
                <span className="font-semibold">“{invitation.guest_name}”</span>. Accept if that was you: its entries and matches move to your account. If it wasn't you, decline.
              </p>
              <div className="flex gap-2">
                <Button disabled={busy} aria-label={`Claim ${invitation.guest_name} at ${invitation.organization_name}`} onClick={() => answer.mutate({ id: invitation.id, accept: true })}>
                  That was me
                </Button>
                <Button variant="outline" disabled={busy} aria-label={`Decline ${invitation.guest_name} at ${invitation.organization_name}`} onClick={() => answer.mutate({ id: invitation.id, accept: false })}>
                  Not me
                </Button>
              </div>
            </li>
          )
        })}
      </ul>

      {past.length > 0 && (
        <section aria-labelledby="claims-heading" className="flex flex-col gap-3">
          <h2 id="claims-heading" className="text-xl font-bold">
            Your claims
          </h2>
          <ul className="flex flex-col gap-2">
            {past.map((claim) => (
              <li key={claim.id} className="rounded-xl border bg-card p-4">
                <p className="font-semibold">
                  {claim.guest_name} · {claim.organization_name}
                </p>
                <p className="text-sm text-muted-foreground">
                  {claim.status === "merged"
                    ? "Done: the matches are on your account."
                    : claim.status === "conflict"
                      ? `Waiting for the club: ${claim.clashes.join("; ")}. Nothing has moved yet.`
                      : "The club decided the guest wasn't you."}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
