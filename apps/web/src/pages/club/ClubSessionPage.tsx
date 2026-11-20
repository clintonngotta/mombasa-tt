import { useDeferredValue, useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, MapPin, UserPlus, X } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { AccessLost } from "@/components/clubs/AccessLost"
import { errorMessage } from "@/lib/api"
import { can, listMembers, useActiveMembership } from "@/lib/clubs"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import {
  cancelClubSession,
  clubSessionKeys,
  getClubSession,
  INVITATION_STATUS,
  inviteMembers,
  listInvitations,
  markAttendance,
  type ClubSession,
  type SessionInvitation,
} from "@/lib/clubSessions"
import { DEFAULT_TIME_ZONE, formatInstant } from "@/lib/dates"
import { cn } from "@/lib/utils"

/** One club session for its training staff: who is invited and coming, inviting more, and attendance. */
export function ClubSessionPage() {
  const { id = "" } = useParams()
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const timeZone = active?.organization.timezone ?? DEFAULT_TIME_ZONE
  const allowed = can(active, "training.manage")
  const session = useQuery({ queryKey: clubSessionKeys.detail(orgId, id), queryFn: () => getClubSession(orgId, id), enabled: allowed })
  const invitations = useQuery({ queryKey: clubSessionKeys.invitations(orgId, id), queryFn: () => listInvitations(orgId, id), enabled: allowed })
  const accessLost = useAdminAccessLost(session.error, invitations.error)
  const s = session.data

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club/sessions">Training sessions</BackLink>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {session.isError && !accessLost && <FormAlert>{errorMessage(session.error, "We couldn't load this session.")}</FormAlert>}
      {allowed && !accessLost && s && (
        <>
          <header className="flex flex-col gap-1">
            <h1 className={cn("text-[32px] leading-9 font-bold", s.status === "cancelled" && "line-through")}>{s.title}</h1>
            <p className="text-lg">
              {formatInstant(s.starts_at, timeZone)} to {formatInstant(s.ends_at, timeZone)}
            </p>
            <p className="flex items-center gap-1.5 text-muted-foreground">
              <MapPin aria-hidden className="size-4" /> {s.tables.map((t) => `${t.label}, ${t.venue_name}`).join(" · ")}
            </p>
            <p className="text-muted-foreground">
              {s.status === "cancelled" ? "Cancelled: members' time and the tables are free again." : `${s.accepted} coming of ${s.invited} invited${s.capacity ? ` · ${s.capacity} places` : ""}`}
            </p>
            {s.notes && <p className="whitespace-pre-wrap">{s.notes}</p>}
          </header>
          <Invited session={s} orgId={orgId} invitations={invitations.data ?? []} error={invitations.error} />
          {s.status === "scheduled" && new Date(s.ends_at) > new Date() && <InviteMembers session={s} orgId={orgId} invited={invitations.data ?? []} />}
          {s.status === "scheduled" && <CancelSession session={s} orgId={orgId} />}
        </>
      )}
    </div>
  )
}

function Invited({ session, orgId, invitations, error }: { session: ClubSession; orgId: string; invitations: SessionInvitation[]; error: unknown }) {
  const queryClient = useQueryClient()
  const started = new Date(session.starts_at) <= new Date()
  const mark = useMutation({
    mutationFn: ({ invitation, attended }: { invitation: SessionInvitation; attended: boolean | null }) => markAttendance(orgId, session.id, invitation.id, attended),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: clubSessionKeys.invitations(orgId, session.id) }),
  })
  return (
    <section aria-labelledby="invited-heading" className="flex flex-col gap-3">
      <h2 id="invited-heading" className="text-xl font-bold">
        Invited
      </h2>
      {error ? <FormAlert>{errorMessage(error, "We couldn't load the invitations.")}</FormAlert> : null}
      {invitations.length === 0 && !error && <p className="text-muted-foreground">Nobody invited yet.</p>}
      {session.status === "scheduled" && !started && invitations.length > 0 && <p className="text-sm text-muted-foreground">Attendance opens when the session starts.</p>}
      {mark.isError && <FormAlert>{errorMessage(mark.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {invitations.map((invitation) => (
          <li key={invitation.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate font-semibold">{invitation.display_name}</span>
              <span className="text-sm text-muted-foreground">
                {INVITATION_STATUS[invitation.status]}
                {invitation.attended === true && " · came"}
                {invitation.attended === false && " · didn't come"}
              </span>
            </span>
            {session.status === "scheduled" && started && (
              <div role="group" aria-label={`Did ${invitation.display_name} come?`} className="flex gap-1">
                <Button size="sm" variant={invitation.attended === true ? "default" : "outline"} aria-pressed={invitation.attended === true} disabled={mark.isPending} onClick={() => mark.mutate({ invitation, attended: invitation.attended === true ? null : true })}>
                  <Check aria-hidden className="size-4" /> Came
                </Button>
                <Button size="sm" variant={invitation.attended === false ? "default" : "outline"} aria-pressed={invitation.attended === false} disabled={mark.isPending} onClick={() => mark.mutate({ invitation, attended: invitation.attended === false ? null : false })}>
                  <X aria-hidden className="size-4" /> Absent
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function InviteMembers({ session, orgId, invited }: { session: ClubSession; orgId: string; invited: SessionInvitation[] }) {
  const queryClient = useQueryClient()
  const [term, setTerm] = useState("")
  const search = useDeferredValue(term.trim())
  const [chosen, setChosen] = useState<string[]>([])
  const members = useQuery({ queryKey: ["clubs", orgId, "members", search], queryFn: () => listMembers(orgId, search) })
  const already = new Set(invited.map((i) => i.user_id))
  const options = (members.data?.results ?? []).filter((m) => !already.has(m.user)).map((m) => ({ value: m.user, label: m.display_name }))
  const send = useMutation({
    mutationFn: () => inviteMembers(orgId, session.id, chosen),
    onSuccess: () => {
      setChosen([])
      void queryClient.invalidateQueries({ queryKey: clubSessionKeys.all })
    },
  })
  return (
    <section aria-labelledby="invite-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="invite-heading" className="flex items-center gap-2 text-xl font-bold">
        <UserPlus aria-hidden className="size-5 text-brand-blue" /> Invite members
      </h2>
      <p className="text-sm text-muted-foreground">An invitation holds nothing: a member's time is kept only when they accept.</p>
      <label className="sr-only" htmlFor="member-search">
        Find a member
      </label>
      <Input id="member-search" type="search" placeholder="Find a member" value={term} onChange={(e) => setTerm(e.target.value)} />
      {members.isError && <FormAlert>{errorMessage(members.error, "We couldn't load the members.")}</FormAlert>}
      {members.isSuccess && options.length === 0 ? (
        <p className="text-muted-foreground">{search ? "No member by that name left to invite." : "Everyone listed is invited."}</p>
      ) : (
        <ChoiceGroup legend="Members" multiple options={options} value={chosen} onChange={setChosen} />
      )}
      {send.isError && <FormAlert>{errorMessage(send.error)}</FormAlert>}
      <Button className="self-start" disabled={!chosen.length || send.isPending} onClick={() => send.mutate()}>
        {send.isPending ? "Inviting…" : chosen.length ? `Invite ${chosen.length}` : "Invite"}
      </Button>
    </section>
  )
}

function CancelSession({ session, orgId }: { session: ClubSession; orgId: string }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const cancel = useMutation({
    mutationFn: () => cancelClubSession(orgId, session.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: clubSessionKeys.all }),
  })
  return (
    <section className="flex flex-col gap-2">
      {cancel.isError && <FormAlert>{errorMessage(cancel.error)}</FormAlert>}
      {confirming ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-destructive/40 p-4">
          <p className="flex-1">Cancel this session? The tables and everyone's time are freed. This can't be undone.</p>
          <Button variant="destructive" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
            Cancel session
          </Button>
          <Button variant="ghost" onClick={() => setConfirming(false)}>
            Keep it
          </Button>
        </div>
      ) : (
        <Button variant="outline" className="self-start text-destructive" onClick={() => setConfirming(true)}>
          Cancel this session
        </Button>
      )}
    </section>
  )
}
