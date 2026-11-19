import { useState, type FormEvent, type ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Banknote, CalendarClock, ChevronRight, ClipboardList, Clock, KeyRound, Landmark, LogOut, Mail, Map, MapPin, Plus, Search, ShieldCheck, Store, Trophy, UserRoundPlus, Users } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { LocationFields } from "@/components/forms/LocationFields"
import { PlaceDirections, PlaceFinderFields } from "@/components/forms/PlaceFinderFields"
import { placeFinderBody, placeFinderErrors, placeFinderFrom } from "@/lib/place"
import { OrganizationCard } from "@/components/clubs/OrganizationCard"
import { RegionFeed } from "@/components/region/RegionFeed"
import { ApiError, errorMessage } from "@/lib/api"
import {
  can,
  clubKeys,
  decideJoinRequest,
  getMyFieldValues,
  leaveOrganization,
  listInvitations,
  listJoinRequests,
  listMyAdminNominations,
  listMyInvitations,
  listMyJoinRequests,
  revokeInvitation,
  roleNames,
  saveMyFieldValues,
  sendInvitation,
  useActiveMembership,
  updateOrganizationLocation,
  type JoinDecision,
  type Membership,
  type Organization,
} from "@/lib/clubs"
import { locationErrors } from "@/lib/geography"
import { tournamentKeys } from "@/lib/tournaments"
import { cn } from "@/lib/utils"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { AccessLost } from "@/components/clubs/AccessLost"
import { MemberFieldValuesForm } from "@/components/clubs/MemberFieldValuesForm"

export function ClubPage() {
  const { memberships, active } = useActiveMembership()
  const myInvitations = useQuery({ queryKey: clubKeys.myInvitations, queryFn: listMyInvitations })
  const invitationCount = myInvitations.data?.count ?? 0
  const myNominations = useQuery({ queryKey: clubKeys.myAdminNominations, queryFn: listMyAdminNominations })
  const nominationCount = myNominations.data?.count ?? 0
  const myRequests = useQuery({ queryKey: clubKeys.myJoinRequests, queryFn: listMyJoinRequests })
  const pendingRequests = myRequests.data?.results.filter((r) => r.status === "pending") ?? []

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[32px] leading-9 font-bold">{active?.organization.name ?? "Club"}</h1>
        <div className="flex gap-2">
          <Link to="/club/find" className={buttonVariants({ variant: "outline" })}>
            <Search aria-hidden className="size-5" /> Find a club
          </Link>
          <Link to="/club/new" className={buttonVariants({ variant: "outline" })}>
            <Plus aria-hidden className="size-5" /> Register
          </Link>
        </div>
      </div>

      {invitationCount > 0 && (
        <Link
          to="/club/invitations"
          className="flex items-center gap-3 rounded-xl border border-brand-blue bg-surface-selected p-4 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Mail aria-hidden className="size-5 text-brand-blue" />
          You have {invitationCount} invitation{invitationCount > 1 && "s"} to join a club. Review
        </Link>
      )}
      {nominationCount > 0 && (
        <Link
          to="/club/admin-nominations"
          className="flex items-center gap-3 rounded-xl border border-brand-blue bg-surface-selected p-4 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <ShieldCheck aria-hidden className="size-5 text-brand-blue" />
          You're nominated as a club admin. Review
        </Link>
      )}
      {myInvitations.isError && <FormAlert>{errorMessage(myInvitations.error, "We couldn't check for club invitations.")}</FormAlert>}

      {memberships.isPending && <p className="text-muted-foreground">Loading your clubs…</p>}
      {memberships.isError && <FormAlert>{errorMessage(memberships.error, "We couldn't load your clubs.")}</FormAlert>}
      {memberships.isSuccess && !active && (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-card p-6">
          <p className="font-semibold">You haven't joined a club yet.</p>
          <p className="text-muted-foreground">Find your club and ask to join, or register one you run.</p>
        </div>
      )}

      {active && <ActiveOrganization key={active.organization.id} membership={active} />}
      {active && !active.managedOnly && active.organization.kind !== "regional_body" && <RegionFeed />}

      {pendingRequests.length > 0 && (
        <section aria-labelledby="my-requests-heading" className="flex flex-col gap-3">
          <h2 id="my-requests-heading" className="text-xl font-bold">
            Your join requests
          </h2>
          <ul className="flex flex-col gap-2">
            {pendingRequests.map((request) => (
              <li key={request.id}>
                <OrganizationCard organization={request.organization}>
                  <span className="flex items-center gap-1 text-sm font-semibold text-warning">
                    <Clock aria-hidden className="size-4" /> Pending
                  </span>
                </OrganizationCard>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}


/** "Showing 20 of 34" when the list is longer than one page. */
function PageNote({ shown, count, hint }: { shown: number; count: number; hint: string }) {
  if (count <= shown) return null
  return (
    <p className="text-sm text-muted-foreground">
      Showing {shown} of {count}. {hint}
    </p>
  )
}

function ActiveOrganization({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const isAdmin = membership.roles.some((role) => role.key === "admin")
  const manageMembers = can(membership, "members.manage")
  const manageRoles = can(membership, "roles.manage")
  const manageCompetitions = can(membership, "competitions.manage")
  const manageFacilities = can(membership, "facilities.manage")
  const manageTraining = can(membership, "training.manage")
  const seeFinances = can(membership, "finances.view", "finances.manage")
  return (
    <>
      <OrganizationCard organization={membership.organization}>
        <span className={cn("flex items-center gap-1 text-sm font-semibold", isAdmin ? "text-brand-blue" : "text-muted-foreground")}>
          {isAdmin && <ShieldCheck aria-hidden className="size-4" />}
          {membership.authority === "platform" ? "Platform super admin" : membership.authority === "country" ? "Country official" : membership.authority === "regional" ? "Regional official" : roleNames(membership.roles)}
        </span>
      </OrganizationCard>
      <PlaceDirections place={membership.organization} className="-mt-2 px-1" />
      {manageRoles && <ClubLocation organization={membership.organization} />}
      {(manageMembers || manageRoles || manageCompetitions || manageFacilities || manageTraining || seeFinances) && (
        <nav aria-label="Club administration" className="flex flex-col gap-2">
          {(manageRoles || manageTraining) && (
            <AdminLink to="/club/profile" icon={<Store aria-hidden className="size-5 text-brand-blue" />}>
              Club profile and training hours
            </AdminLink>
          )}
          {manageTraining && (
            <AdminLink to="/club/sessions" icon={<CalendarClock aria-hidden className="size-5 text-brand-blue" />}>
              Training sessions: invitations and attendance
            </AdminLink>
          )}
          {manageCompetitions && (
            <AdminLink to="/club/tournaments" icon={<Trophy aria-hidden className="size-5 text-brand-blue" />}>
              Tournaments
            </AdminLink>
          )}
          {manageFacilities && (
            <AdminLink to="/club/venues" icon={<MapPin aria-hidden className="size-5 text-brand-blue" />}>
              Venues and tables
            </AdminLink>
          )}
          {(membership.organization.kind === "facility" || membership.organization.kind === "club_facility") && seeFinances && (
            <AdminLink to="/club/takings" icon={<Banknote aria-hidden className="size-5 text-brand-blue" />}>
              Door takings
            </AdminLink>
          )}
          {(manageMembers || manageRoles) && (
            <AdminLink to="/club/members" icon={<Users aria-hidden className="size-5 text-brand-blue" />}>
              Members and their roles
            </AdminLink>
          )}
          {(manageMembers || manageCompetitions) && (
            <AdminLink to="/club/guests" icon={<UserRoundPlus aria-hidden className="size-5 text-brand-blue" />}>
              Guests and their claims
            </AdminLink>
          )}
          {manageRoles && (
            <AdminLink to="/club/roles" icon={<KeyRound aria-hidden className="size-5 text-brand-blue" />}>
              Roles and permissions
            </AdminLink>
          )}
          {manageMembers && (
            <AdminLink to="/club/fields" icon={<ClipboardList aria-hidden className="size-5 text-brand-blue" />}>
              Member fields
            </AdminLink>
          )}
        </nav>
      )}
      {membership.organization.kind === "regional_body" && (
        <AdminLink to="/region" icon={<Map aria-hidden className="size-5 text-brand-blue" />}>
          Region: agenda, clubs, articles, meetings, sponsorships and approvals
        </AdminLink>
      )}
      <AdminLink to="/club/committee" icon={<Landmark aria-hidden className="size-5 text-brand-blue" />}>
        {can(membership, "governance.manage") ? "Committee and its positions" : "Committee"}
      </AdminLink>
      {!membership.managedOnly && (
        <AdminLink to="/club/meetings" icon={<CalendarClock aria-hidden className="size-5 text-brand-blue" />}>
          Meetings
        </AdminLink>
      )}
      {!membership.managedOnly && <MyClubDetails membershipId={membership.id} />}
      {manageMembers && (
        <>
          <JoinRequestsPanel orgId={orgId} />
          <InvitationsPanel orgId={orgId} />
        </>
      )}
      {!membership.managedOnly && <LeaveOrganization membership={membership} />}
    </>
  )
}

function ClubLocation({ organization }: { organization: Organization }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [location, setLocation] = useState({
    country: organization.country, region: organization.region, city: organization.town,
  })
  const [finder, setFinder] = useState(() => placeFinderFrom(organization))
  const save = useMutation({
    mutationFn: () => updateOrganizationLocation(organization.id, {
      country: location.country, region: location.region, town: location.city, ...placeFinderBody(finder),
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: clubKeys.all }),
        queryClient.invalidateQueries({ queryKey: tournamentKeys.all }),
      ])
      setEditing(false)
    },
  })
  const missing = { ...locationErrors(location), ...placeFinderErrors(finder) }
  const fields = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  if (!editing) {
    return (
      <Button type="button" variant="outline" className="self-start" onClick={() => {
        setLocation({ country: organization.country, region: organization.region, city: organization.town })
        setFinder(placeFinderFrom(organization))
        setSubmitted(false)
        save.reset()
        setEditing(true)
      }}>
        {organization.country ? "Edit club location" : "Set club location"}
      </Button>
    )
  }

  return (
    <form className="flex flex-col gap-3 rounded-xl border bg-card p-4" noValidate onSubmit={(event) => {
      event.preventDefault()
      setSubmitted(true)
      if (Object.keys(missing).length === 0) save.mutate()
    }}>
      <LocationFields value={location} onChange={setLocation} errors={submitted ? { ...fields, ...missing } : fields} cityLimit={80} />
      <PlaceFinderFields value={finder} onChange={setFinder} errors={submitted ? { ...fields, ...missing } : fields} place={organization.kind === "facility" ? "facility" : "club"} />
      {save.isError && Object.keys(fields).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending}>Save location</Button>
        <Button type="button" variant="ghost" onClick={() => setEditing(false)} disabled={save.isPending}>Cancel</Button>
      </div>
    </form>
  )
}

/** The member's own answers to the club's member-visible fields (REQ-005). Hidden when the club asks for none. */
function MyClubDetails({ membershipId }: { membershipId: string }) {
  const queryClient = useQueryClient()
  const key = clubKeys.myFieldValues(membershipId)
  const details = useQuery({ queryKey: key, queryFn: () => getMyFieldValues(membershipId) })
  if (details.isError) return <FormAlert>{errorMessage(details.error, "We couldn't load your club details.")}</FormAlert>
  if (!details.data?.length) return null
  const missing = details.data.filter((entry) => entry.field.required && entry.value === null).length
  return (
    <section aria-labelledby="my-details-heading" className="flex flex-col gap-3">
      <h2 id="my-details-heading" className="text-xl font-bold">
        Your club details
      </h2>
      <p className="text-sm text-muted-foreground">
        Asked for by this club and seen by you and the people who manage its members.
        {missing > 0 && ` ${missing} required ${missing === 1 ? "answer is" : "answers are"} missing.`}
      </p>
      <div className="rounded-xl border bg-card p-4">
        <MemberFieldValuesForm
          entries={details.data}
          save={(values) => saveMyFieldValues(membershipId, values)}
          onSaved={(entries) => queryClient.setQueryData(key, entries)}
        />
      </div>
    </section>
  )
}

function AdminLink({ to, icon, children }: { to: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link to={to} className={cn(ROW, "min-h-12 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
      {icon}
      <span className="flex-1">{children}</span>
      <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
    </Link>
  )
}

/** Two-step leave so a stray tap can't drop someone out of their club. */
function LeaveOrganization({ membership }: { membership: Membership }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const name = membership.organization.name
  const leave = useMutation({
    mutationFn: () => leaveOrganization(membership.id),
    onSuccess: () => navigate("/club"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.all }),
  })
  return (
    <section aria-label={`Leave ${name}`} className="flex flex-col gap-2 border-t pt-4">
      {leave.isError && <FormAlert>{errorMessage(leave.error)}</FormAlert>}
      {confirming ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-sm">Leave {name}? Your roles there end and you'd need to ask to join again.</p>
          <Button variant="outline" onClick={() => setConfirming(false)}>
            Stay
          </Button>
          <Button variant="destructive" disabled={leave.isPending} onClick={() => leave.mutate()}>
            {leave.isPending ? "Leaving…" : "Leave club"}
          </Button>
        </div>
      ) : (
        <Button variant="ghost" className="self-start text-muted-foreground" onClick={() => setConfirming(true)}>
          <LogOut aria-hidden className="size-5" /> Leave {name}
        </Button>
      )}
    </section>
  )
}

function JoinRequestsPanel({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const requests = useQuery({ queryKey: clubKeys.joinRequests(orgId), queryFn: () => listJoinRequests(orgId) })
  const decide = useMutation({
    mutationFn: ({ id, outcome }: { id: string; outcome: JoinDecision }) => decideJoinRequest(orgId, id, outcome),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.joinRequests(orgId) }),
  })
  const items = requests.data?.results ?? []
  const accessLost = useAdminAccessLost(requests.error, decide.error)

  return (
    <section aria-labelledby="join-requests-heading" className="flex flex-col gap-3">
      <h2 id="join-requests-heading" className="text-xl font-bold">
        Join requests
      </h2>
      {accessLost && <AccessLost />}
      {requests.isPending && <p className="text-muted-foreground">Loading requests…</p>}
      {requests.isError && !accessLost && <FormAlert>{errorMessage(requests.error, "We couldn't load join requests.")}</FormAlert>}
      {decide.isError && !accessLost && <FormAlert>{errorMessage(decide.error)}</FormAlert>}
      {requests.isSuccess && items.length === 0 && <p className="text-muted-foreground">No one is waiting to join.</p>}
      <ul className="flex flex-col gap-2">
        {items.map((request) => {
          const busy = decide.isPending && decide.variables?.id === request.id
          const name = request.display_name || "Unnamed player"
          return (
            <li key={request.id} className={ROW}>
              <span className="flex-1 font-semibold">{name}</span>
              <Button variant="outline" disabled={busy} aria-label={`Decline ${name}`} onClick={() => decide.mutate({ id: request.id, outcome: "reject" })}>
                Decline
              </Button>
              <Button disabled={busy} aria-label={`Approve ${name}`} onClick={() => decide.mutate({ id: request.id, outcome: "approve" })}>
                Approve
              </Button>
            </li>
          )
        })}
      </ul>
      {requests.data && <PageNote shown={items.length} count={requests.data.count} hint="Oldest first; settle these to see the rest." />}
    </section>
  )
}

function InvitationsPanel({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState("")
  const [sentTo, setSentTo] = useState<string | null>(null)
  const invitations = useQuery({ queryKey: clubKeys.invitations(orgId), queryFn: () => listInvitations(orgId) })
  const refresh = () => queryClient.invalidateQueries({ queryKey: clubKeys.invitations(orgId) })

  const send = useMutation({
    mutationFn: (email: string) => sendInvitation(orgId, { email }),
    onSuccess: (invitation) => {
      setSentTo(invitation.email)
      setEmail("")
      refresh()
    },
  })
  const revoke = useMutation({ mutationFn: (id: string) => revokeInvitation(orgId, id), onSettled: refresh })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSentTo(null)
    send.mutate(email.trim())
  }

  const emailError = send.error instanceof ApiError ? send.error.fieldErrors().email : undefined
  const items = invitations.data?.results ?? []
  const accessLost = useAdminAccessLost(invitations.error, send.error, revoke.error)

  return (
    <section aria-labelledby="invitations-heading" className="flex flex-col gap-3">
      <h2 id="invitations-heading" className="text-xl font-bold">
        Invitations
      </h2>
      <form onSubmit={onSubmit} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
        <Field
          label="Invite by email"
          type="email"
          autoComplete="off"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={emailError}
          hint="They join only after accepting. Invitations expire after 14 days."
        />
        {send.isError && !emailError && !accessLost && <FormAlert>{errorMessage(send.error)}</FormAlert>}
        {sentTo && (
          <p role="status" className="text-sm text-success">
            Invitation sent to {sentTo}.
          </p>
        )}
        <Button type="submit" className="self-start" disabled={send.isPending}>
          {send.isPending ? "Sending…" : "Send invitation"}
        </Button>
      </form>

      {accessLost && <AccessLost />}
      {invitations.isPending && <p className="text-muted-foreground">Loading invitations…</p>}
      {invitations.isError && !accessLost && <FormAlert>{errorMessage(invitations.error, "We couldn't load invitations.")}</FormAlert>}
      {revoke.isError && !accessLost && <FormAlert>{errorMessage(revoke.error)}</FormAlert>}
      {invitations.isSuccess && items.length === 0 && <p className="text-muted-foreground">No open invitations.</p>}
      {items.length > 0 && (
        <ul aria-label="Pending invitations" className="flex flex-col gap-2">
          {items.map((invitation) => (
            <li key={invitation.id} className={ROW}>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{invitation.email}</span>
                <span className="text-sm text-muted-foreground">
                  Pending · expires {new Date(invitation.expires_at).toLocaleDateString("en-KE", { day: "numeric", month: "short" })}
                </span>
              </span>
              <Button
                variant="outline"
                aria-label={`Revoke invitation to ${invitation.email}`}
                disabled={revoke.isPending && revoke.variables === invitation.id}
                onClick={() => revoke.mutate(invitation.id)}
              >
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}
      {invitations.data && <PageNote shown={items.length} count={invitations.data.count} hint="Newest first." />}
    </section>
  )
}
