import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { MapPin, UserCheck, Users } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ConflictList } from "@/components/training/ConflictList"
import { ApiError, errorMessage } from "@/lib/api"
import { acceptInvitation, apologiseForSession, checkInAtSession, clashesOf, clubSessionKeys, declineInvitation, INVITATION_STATUS, listMyInvitations, type MySessionInvitation } from "@/lib/clubSessions"
import { locate } from "@/lib/nearby"
import { formatInstant } from "@/lib/dates"
import { LOCAL_TIME_ZONE, trainingKeys } from "@/lib/training"
import { ROW } from "@/lib/clubAdmin"

/** Club sessions the member is invited to (REQ-027). Accepting keeps the time in their calendar; until then
 * nothing is held. */
export function ClubInvitations() {
  // Staff move sessions and check-in opens by the clock, so read the list fresh each time.
  const invitations = useQuery({ queryKey: clubSessionKeys.mine("upcoming"), queryFn: () => listMyInvitations("upcoming"), staleTime: 0 })
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
  const place = invitation.check_in.place
  const [now] = useState(() => Date.now())
  const open = now >= new Date(invitation.check_in.opens_at).getTime() && now <= new Date(invitation.check_in.closes_at).getTime()
  const canCheckIn = !cancelled && open && invitation.attended == null && invitation.status !== "declined"
  // The position is read for this one request and not held in the page afterwards.
  const checkIn = useMutation({ mutationFn: async () => checkInAtSession(invitation.id, await locate({ fresh: true })), onSuccess: refresh })
  const [apologising, setApologising] = useState(false)
  const [reason, setReason] = useState("")
  const apologise = useMutation({
    mutationFn: () => apologiseForSession(invitation.id, reason.trim()),
    onSuccess: () => {
      setApologising(false)
      refresh()
    },
  })
  const started = now >= new Date(session.starts_at).getTime()
  const clashes = clashesOf(accept.error)
  const failed = accept.error ?? decline.error ?? apologise.error

  return (
    <div className={`${ROW} flex-col items-stretch`}>
      <div className="flex flex-col gap-0.5">
        <p className="font-semibold">
          {session.title} <span className="font-normal text-muted-foreground">· {session.organization_name}</span>
        </p>
        <p>
          {formatInstant(session.starts_at, LOCAL_TIME_ZONE)} to {formatInstant(session.ends_at, LOCAL_TIME_ZONE)}
        </p>
        {place?.moved ? (
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <MapPin aria-hidden className="size-4 text-brand-blue" /> Moved: now at {place.label || "another place"}
          </p>
        ) : (
          (place?.label || session.tables.length > 0) && (
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <MapPin aria-hidden className="size-4" /> {place?.label || session.tables[0].venue_name}
            </p>
          )
        )}
        {session.notes && <p className="text-sm whitespace-pre-wrap">{session.notes}</p>}
        <p className="text-sm font-semibold">
          {cancelled ? "Cancelled by the club" : invitation.apologised ? `You sent an apology${invitation.apology_reason ? `: ${invitation.apology_reason}` : ""}` : INVITATION_STATUS[invitation.status]}
          {!cancelled && invitation.status === "invited" && session.full && " · full"}
        </p>
      </div>
      <ConflictList conflicts={clashes} timeZone={LOCAL_TIME_ZONE} lead="You already have something on then:" next="Move it, or decline this session." />
      {failed && !clashes.length && <FormAlert>{errorMessage(failed)}</FormAlert>}
      {!cancelled && invitation.attended === true && (
        <p role="status" className="flex items-center gap-1.5 font-semibold">
          <UserCheck aria-hidden className="size-5 text-brand-blue" />
          {invitation.attendance_source === "staff" ? "The coach marked you present" : "You're checked in"}
          {invitation.late && " (late)"}
        </p>
      )}
      {canCheckIn && (
        <div className="flex flex-col gap-2 rounded-lg border border-brand-blue/30 bg-surface-selected p-3">
          <p className="text-sm">
            {place ? `Check-in is open. You need to be within ${invitation.check_in.radius_m} m of ${place.label || "the session"}; your phone will ask for your location.` : "The club hasn't set where it trains, so the coach marks attendance."}
          </p>
          {place && (
            <Button className="self-start" disabled={checkIn.isPending} onClick={() => checkIn.mutate()}>
              <UserCheck aria-hidden className="size-4" /> {checkIn.isPending ? "Checking where you are…" : "Check in"}
            </Button>
          )}
          {checkIn.isError && <FormAlert>{checkIn.error instanceof ApiError ? errorMessage(checkIn.error) : checkIn.error instanceof Error ? checkIn.error.message : errorMessage(checkIn.error)}</FormAlert>}
          {place && <p className="text-xs text-muted-foreground">Your location is used for this check only. Only your distance from the session is kept.</p>}
        </div>
      )}
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
          {!started && !invitation.apologised && invitation.attended == null && !apologising && (
            <Button variant="outline" onClick={() => setApologising(true)}>
              Send an apology
            </Button>
          )}
        </div>
      )}
      {!cancelled && apologising && (
        <div className="flex flex-col gap-2 rounded-lg border p-3">
          <Field label="Why you can't come" optional maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="The coach sees this. You're recorded as apologised, not absent." />
          <div className="flex flex-wrap gap-2">
            <Button disabled={apologise.isPending} onClick={() => apologise.mutate()}>
              {apologise.isPending ? "Sending…" : "Send apology"}
            </Button>
            <Button variant="ghost" onClick={() => setApologising(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
