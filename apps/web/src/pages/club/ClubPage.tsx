import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Mail, Plus, Search, ShieldCheck } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { OrganizationCard } from "@/components/clubs/OrganizationCard"
import { ApiError, errorMessage } from "@/lib/api"
import {
  clubKeys,
  decideJoinRequest,
  invite,
  listInvitations,
  listJoinRequests,
  listMyInvitations,
  revokeInvitation,
  useActiveMembership,
  type Membership,
} from "@/lib/clubs"
import { cn } from "@/lib/utils"

export function ClubPage() {
  const { memberships, active } = useActiveMembership()
  const myInvitations = useQuery({ queryKey: clubKeys.myInvitations, queryFn: listMyInvitations })
  const invitationCount = myInvitations.data?.count ?? 0

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

      {memberships.isPending && <p className="text-muted-foreground">Loading your clubs…</p>}
      {memberships.isError && <FormAlert>{errorMessage(memberships.error, "We couldn't load your clubs.")}</FormAlert>}
      {memberships.isSuccess && !active && (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-card p-6">
          <p className="font-semibold">You haven't joined a club yet.</p>
          <p className="text-muted-foreground">
            Find your club and ask to join, or register one you run. You can enter public tournaments without joining
            the host club.
          </p>
        </div>
      )}

      {active && <ActiveOrganization membership={active} />}
    </div>
  )
}

function ActiveOrganization({ membership }: { membership: Membership }) {
  const isAdmin = membership.role === "admin"
  return (
    <>
      <OrganizationCard organization={membership.organization}>
        <span className={cn("flex items-center gap-1 text-sm font-semibold", isAdmin ? "text-brand-blue" : "text-muted-foreground")}>
          {isAdmin && <ShieldCheck aria-hidden className="size-4" />}
          {isAdmin ? "Admin" : "Member"}
        </span>
      </OrganizationCard>
      {isAdmin && (
        <>
          <JoinRequestsPanel orgId={membership.organization.id} />
          <InvitationsPanel orgId={membership.organization.id} />
        </>
      )}
    </>
  )
}

function JoinRequestsPanel({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const requests = useQuery({ queryKey: clubKeys.joinRequests(orgId), queryFn: () => listJoinRequests(orgId) })
  const decide = useMutation({
    mutationFn: ({ id, outcome }: { id: string; outcome: "approve" | "reject" }) => decideJoinRequest(orgId, id, outcome),
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.joinRequests(orgId) }),
  })
  const items = requests.data?.results ?? []

  return (
    <section aria-labelledby="join-requests-heading" className="flex flex-col gap-3">
      <h2 id="join-requests-heading" className="text-xl font-bold">
        Join requests
      </h2>
      {requests.isPending && <p className="text-muted-foreground">Loading requests…</p>}
      {requests.isError && <FormAlert>{errorMessage(requests.error, "We couldn't load join requests.")}</FormAlert>}
      {decide.isError && <FormAlert>{errorMessage(decide.error)}</FormAlert>}
      {requests.isSuccess && items.length === 0 && <p className="text-muted-foreground">No one is waiting to join.</p>}
      <ul className="flex flex-col gap-2">
        {items.map((request) => {
          const busy = decide.isPending && decide.variables?.id === request.id
          return (
            <li key={request.id} className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4">
              <span className="flex-1 font-semibold">{request.display_name || "Unnamed player"}</span>
              <Button variant="outline" disabled={busy} onClick={() => decide.mutate({ id: request.id, outcome: "reject" })}>
                Decline
              </Button>
              <Button disabled={busy} onClick={() => decide.mutate({ id: request.id, outcome: "approve" })}>
                Approve
              </Button>
            </li>
          )
        })}
      </ul>
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
    mutationFn: (address: string) => invite(orgId, address),
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
        {send.isError && !emailError && <FormAlert>{errorMessage(send.error)}</FormAlert>}
        {sentTo && (
          <p role="status" className="text-sm text-success">
            Invitation sent to {sentTo}.
          </p>
        )}
        <Button type="submit" className="self-start" disabled={send.isPending}>
          {send.isPending ? "Sending…" : "Send invitation"}
        </Button>
      </form>

      {invitations.isError && <FormAlert>{errorMessage(invitations.error, "We couldn't load invitations.")}</FormAlert>}
      {revoke.isError && <FormAlert>{errorMessage(revoke.error)}</FormAlert>}
      {items.length > 0 && (
        <ul aria-label="Pending invitations" className="flex flex-col gap-2">
          {items.map((invitation) => (
            <li key={invitation.id} className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4">
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{invitation.email}</span>
                <span className="text-sm text-muted-foreground">
                  Pending · expires {new Date(invitation.expires_at).toLocaleDateString("en-KE", { day: "numeric", month: "short" })}
                </span>
              </span>
              <Button
                variant="outline"
                disabled={revoke.isPending && revoke.variables === invitation.id}
                onClick={() => revoke.mutate(invitation.id)}
              >
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
