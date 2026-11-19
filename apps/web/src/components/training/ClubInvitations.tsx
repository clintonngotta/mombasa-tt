import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { MapPin, Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { ConflictList } from "@/components/training/ConflictList"
import { errorMessage } from "@/lib/api"
import { acceptInvitation, clashesOf, clubSessionKeys, declineInvitation, INVITATION_STATUS, listMyInvitations, type MySessionInvitation } from "@/lib/clubSessions"
import { formatInstant } from "@/lib/dates"
import { LOCAL_TIME_ZONE, trainingKeys } from "@/lib/training"
import { ROW } from "@/lib/clubAdmin"

/** Club sessions the member is invited to (REQ-027). Accepting keeps the time in their calendar; until then
 * nothing is held. */
export function ClubInvitations() {
  const invitations = useQuery({ queryKey: clubSessionKeys.mine("upcoming"), queryFn: () => listMyInvitations("upcoming") })
  const items = invitations.data?.results ?? []
  if (invitations.isSuccess && items.length === 0) return null
  return (
    <section aria-labelledby="club-sessions-heading" className="flex flex-col gap-3">
      <h2 id="club-sessions-heading" className="flex items-center gap-2 text-xl font-bold">
        <Users aria-hidden className="size-5 text-brand-blue" /> Club sessions
      </h2>
      {invitations.isError && <FormAlert>{errorMessage(invitations.error, "We couldn't load your club sessions.")}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {items.map((invitation) => (
          <li key={invitation.id}>
            <Invitation invitation={invitation} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function Invitation({ invitation }: { invitation: MySessionInvitation }) {
  const queryClient = useQueryClient()
  const { session } = invitation
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: clubSessionKeys.all })
    void queryClient.invalidateQueries({ queryKey: trainingKeys.all })
  }
  const accept = useMutation({ mutationFn: () => acceptInvitation(invitation.id), onSuccess: refresh })
  const decline = useMutation({ mutationFn: () => declineInvitation(invitation.id), onSuccess: refresh })
  const cancelled = session.status === "cancelled"
  const clashes = clashesOf(accept.error)
  const failed = accept.error ?? decline.error

  return (
    <div className={`${ROW} flex-col items-stretch`}>
      <div className="flex flex-col gap-0.5">
        <p className="font-semibold">
          {session.title} <span className="font-normal text-muted-foreground">· {session.organization_name}</span>
        </p>
        <p>
          {formatInstant(session.starts_at, LOCAL_TIME_ZONE)} to {formatInstant(session.ends_at, LOCAL_TIME_ZONE)}
        </p>
        {session.tables.length > 0 && (
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <MapPin aria-hidden className="size-4" /> {session.tables[0].venue_name}
          </p>
        )}
        {session.notes && <p className="text-sm whitespace-pre-wrap">{session.notes}</p>}
        <p className="text-sm font-semibold">
          {cancelled ? "Cancelled by the club" : INVITATION_STATUS[invitation.status]}
          {!cancelled && invitation.status === "invited" && session.full && " · full"}
        </p>
      </div>
      <ConflictList conflicts={clashes} timeZone={LOCAL_TIME_ZONE} lead="You already have something on then:" next="Move it, or decline this session." />
      {failed && !clashes.length && <FormAlert>{errorMessage(failed)}</FormAlert>}
      {!cancelled && (
        <div className="flex flex-wrap gap-2">
          {invitation.status !== "accepted" && (
            <Button disabled={accept.isPending || session.full} onClick={() => accept.mutate()}>
              {accept.isPending ? "Saving…" : "I'm coming"}
            </Button>
          )}
          {invitation.status !== "declined" && (
            <Button variant="outline" disabled={decline.isPending} onClick={() => decline.mutate()}>
              {invitation.status === "accepted" ? "I can't come after all" : "Can't come"}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
