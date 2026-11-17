import { useState, type FormEvent, type ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, Clock, KeyRound, LogOut, Mail, Plus, Search, ShieldCheck, Users } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { OrganizationCard } from "@/components/clubs/OrganizationCard"
import { ApiError, errorMessage } from "@/lib/api"
import {
  can,
  clubKeys,
  decideJoinRequest,
  leaveOrganization,
  listInvitations,
  listJoinRequests,
  listMyInvitations,
  listMyJoinRequests,
  revokeInvitation,
  roleNames,
  sendInvitation,
  useActiveMembership,
  type JoinDecision,
  type Membership,
} from "@/lib/clubs"
import { cn } from "@/lib/utils"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { AccessLost } from "@/components/clubs/AccessLost"

export function ClubPage() {
  const { memberships, active } = useActiveMembership()
  const myInvitations = useQuery({ queryKey: clubKeys.myInvitations, queryFn: listMyInvitations })
  const invitationCount = myInvitations.data?.count ?? 0
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
  return (
    <>
      <OrganizationCard organization={membership.organization}>
        <span className={cn("flex items-center gap-1 text-sm font-semibold", isAdmin ? "text-brand-blue" : "text-muted-foreground")}>
          {isAdmin && <ShieldCheck aria-hidden className="size-4" />}
          {roleNames(membership.roles)}
        </span>
      </OrganizationCard>
      {(manageMembers || manageRoles) && (
        <nav aria-label="Club administration" className="flex flex-col gap-2">
          <AdminLink to="/club/members" icon={<Users aria-hidden className="size-5 text-brand-blue" />}>
            Members and their roles
          </AdminLink>
          {manageRoles && (
            <AdminLink to="/club/roles" icon={<KeyRound aria-hidden className="size-5 text-brand-blue" />}>
              Roles and permissions
            </AdminLink>
          )}
        </nav>
      )}
      {manageMembers && (
        <>
          <JoinRequestsPanel orgId={orgId} />
          <InvitationsPanel orgId={orgId} />
        </>
      )}
      <LeaveOrganization membership={membership} />
    </>
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
