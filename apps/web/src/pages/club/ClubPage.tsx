import { useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Building2, Clock, LogOut, Mail, Plus, Search, ShieldCheck } from "lucide-react"
import { OrganizationLinks, OrgLinkRow } from "@/components/clubs/OrganizationLinks"
import { actsAsFacility } from "@/lib/navigation"
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
  isBodyKind,
  revokeInvitation,
  roleNames,
  saveMyFieldValues,
  sendInvitation,
  setActiveOrganization,
  SIDE,
  sideOf,
  useActiveMembership,
  updateOrganizationLocation,
  type JoinDecision,
  type Membership,
  type Organization,
  type Side,
} from "@/lib/clubs"
import { locationErrors } from "@/lib/geography"
import { tournamentKeys } from "@/lib/tournaments"
import { cn } from "@/lib/utils"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { AccessLost } from "@/components/clubs/AccessLost"
import { MemberFieldValuesForm } from "@/components/clubs/MemberFieldValuesForm"

/** The Club tab, and with `side="team"` the Team tab (REQ-057): the organization the player is acting
 * for when it is on this side, or the way to one. */
export function ClubPage({ side = "club" }: { side?: Side }) {
  const { memberships, all, active: current } = useActiveMembership()
  const { path, noun, title, plural, start } = SIDE[side]
  const mine = all.filter((m) => sideOf(m.organization.kind) === side)
  const active = current && sideOf(current.organization.kind) === side ? current : undefined
  // Opening the tab with the other side's organization active: a player's only club (or team) opens by
  // itself; with several they choose below.
  const only = !active && mine.length === 1 ? mine[0].organization.id : null
  useEffect(() => {
    if (only) setActiveOrganization(only)
  }, [only])
  const myInvitations = useQuery({ queryKey: clubKeys.myInvitations, queryFn: listMyInvitations })
  const invitationCount = myInvitations.data?.count ?? 0
  const myNominations = useQuery({ queryKey: clubKeys.myAdminNominations, queryFn: listMyAdminNominations })
  const nominationCount = myNominations.data?.count ?? 0
  const myRequests = useQuery({ queryKey: clubKeys.myJoinRequests, queryFn: listMyJoinRequests })
  const pendingRequests = myRequests.data?.results.filter((r) => r.status === "pending" && sideOf(r.organization.kind) === side) ?? []
  const actions = (primary: boolean) => (
    <div className="flex flex-wrap gap-2">
      <Link to={`${path}/find`} className={buttonVariants({ variant: primary ? "default" : "outline" })}>
        <Search aria-hidden className="size-5" /> Find a {noun}
      </Link>
      <Link to={`${path}/new`} className={buttonVariants({ variant: "outline" })}>
        <Plus aria-hidden className="size-5" /> {start}
      </Link>
    </div>
  )

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-[32px] leading-9 font-bold">{active?.organization.name ?? title}</h1>
        {(active || mine.length > 1) && actions(false)}
      </div>

      {invitationCount > 0 && (
        <Link
          to="/club/invitations"
          className="flex items-center gap-3 rounded-xl border border-brand-blue bg-surface-selected p-4 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Mail aria-hidden className="size-5 text-brand-blue" />
          You have {invitationCount} invitation{invitationCount > 1 && "s"} to join a club or team. Review
        </Link>
      )}
      {nominationCount > 0 && (
        <Link
          to="/club/admin-nominations"
          className="flex items-center gap-3 rounded-xl border border-brand-blue bg-surface-selected p-4 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <ShieldCheck aria-hidden className="size-5 text-brand-blue" />
          You're nominated as an admin. Review
        </Link>
      )}
      {myInvitations.isError && <FormAlert>{errorMessage(myInvitations.error, "We couldn't check for invitations.")}</FormAlert>}

      {memberships.isPending && <p className="text-muted-foreground">Loading your {plural}…</p>}
      {memberships.isError && <FormAlert>{errorMessage(memberships.error, `We couldn't load your ${plural}.`)}</FormAlert>}
      {memberships.isSuccess && mine.length === 0 && (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-card p-6">
          <p className="font-semibold">You haven't joined a {noun} yet.</p>
          <p className="text-muted-foreground">
            {side === "team"
              ? "A team is players who play together without a training place of their own. Find yours and ask to join, or form one and invite your teammates."
              : "A club is a place people train at. Find yours and ask to join, or register one you run."}
          </p>
          {actions(true)}
        </div>
      )}
      {!active && mine.length > 1 && (
        <section aria-labelledby="choose-heading" className="flex flex-col gap-3">
          <h2 id="choose-heading" className="text-xl font-bold">
            Your {plural}
          </h2>
          <ul className="flex flex-col gap-2">
            {mine.map(({ organization }) => (
              <li key={organization.id}>
                <OrganizationCard organization={organization}>
                  <Button variant="outline" aria-label={`Open ${organization.name}`} onClick={() => setActiveOrganization(organization.id)}>
                    Open
                  </Button>
                </OrganizationCard>
              </li>
            ))}
          </ul>
        </section>
      )}

      {active && <ActiveOrganization key={active.organization.id} membership={active} />}
      {active && !active.managedOnly && !isBodyKind(active.organization.kind) && <RegionFeed />}

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

export const TeamPage = () => <ClubPage side="team" />


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
  const manageMembers = can(membership, "members.manage")
  const isAdmin = membership.roles.some((role) => role.key === "admin")
  return (
    <>
      <OrganizationCard organization={membership.organization}>
        <span className={cn("flex items-center gap-1 text-sm font-semibold", isAdmin ? "text-brand-blue" : "text-muted-foreground")}>
          {isAdmin && <ShieldCheck aria-hidden className="size-4" />}
          {membership.authority === "platform" ? "Platform super admin" : membership.authority === "country" ? "Country official" : membership.authority === "regional" ? "Regional official" : roleNames(membership.roles)}
        </span>
      </OrganizationCard>
      <PlaceDirections place={membership.organization} className="-mt-2 px-1" />
      {can(membership, "roles.manage") && <ClubLocation organization={membership.organization} />}
      {actsAsFacility(membership) && (
        <OrgLinkRow to="/facility" icon={<Building2 aria-hidden className="size-5 text-brand-blue" />}>
          Open the facility desk
        </OrgLinkRow>
      )}
      <OrganizationLinks membership={membership} variant={membership.organization.kind === "facility" ? "facility" : sideOf(membership.organization.kind)} />
      {!membership.managedOnly && <MyClubDetails membershipId={membership.id} noun={SIDE[sideOf(membership.organization.kind)].noun} />}
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
  // A team has a home town and no training place to find (REQ-057).
  const team = organization.kind === "team"
  const save = useMutation({
    mutationFn: () => updateOrganizationLocation(organization.id, {
      country: location.country, region: location.region, town: location.city, ...(team ? {} : placeFinderBody(finder)),
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: clubKeys.all }),
        queryClient.invalidateQueries({ queryKey: tournamentKeys.all }),
      ])
      setEditing(false)
    },
  })
  const missing = { ...locationErrors(location), ...(team ? {} : placeFinderErrors(finder)) }
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
        {team ? (organization.country ? "Edit home town" : "Set home town") : organization.country ? "Edit club location" : "Set club location"}
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
      {!team && <PlaceFinderFields value={finder} onChange={setFinder} errors={submitted ? { ...fields, ...missing } : fields} place={organization.kind === "facility" ? "facility" : "club"} />}
      {save.isError && Object.keys(fields).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending}>Save location</Button>
        <Button type="button" variant="ghost" onClick={() => setEditing(false)} disabled={save.isPending}>Cancel</Button>
      </div>
    </form>
  )
}

/** The member's own answers to the club's member-visible fields (REQ-005). Hidden when the club asks for none. */
function MyClubDetails({ membershipId, noun }: { membershipId: string; noun: string }) {
  const queryClient = useQueryClient()
  const key = clubKeys.myFieldValues(membershipId)
  const details = useQuery({ queryKey: key, queryFn: () => getMyFieldValues(membershipId) })
  if (details.isError) return <FormAlert>{errorMessage(details.error, `We couldn't load your ${noun} details.`)}</FormAlert>
  if (!details.data?.length) return null
  const missing = details.data.filter((entry) => entry.field.required && entry.value === null).length
  return (
    <section aria-labelledby="my-details-heading" className="flex flex-col gap-3">
      <h2 id="my-details-heading" className="text-xl font-bold">
        Your {noun} details
      </h2>
      <p className="text-sm text-muted-foreground">
        Asked for by this {noun} and seen by you and the people who manage its members.
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

/** Two-step leave so a stray tap can't drop someone out of their club. */
function LeaveOrganization({ membership }: { membership: Membership }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const name = membership.organization.name
  const { path, noun } = SIDE[sideOf(membership.organization.kind)]
  const leave = useMutation({
    mutationFn: () => leaveOrganization(membership.id),
    onSuccess: () => navigate(path),
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
            {leave.isPending ? "Leaving…" : `Leave ${noun}`}
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
