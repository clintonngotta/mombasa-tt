import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Mail, TriangleAlert, UserPlus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import {
  CLAIM_ACTION,
  createGuest,
  guestKeys,
  inviteGuest,
  listGuestClaims,
  listGuests,
  rejectGuestClaim,
  retryGuestClaim,
  revokeGuestInvitation,
  type Guest,
  type GuestClaim,
} from "@/lib/guests"

const when = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })

/**
 * The club's guests (REQ-003): players entered before they had an account. Staff invite the person by
 * email; once they accept with that verified address, the guest's entries and matches move to their
 * account. A claim that clashes waits here for staff to resolve, with its trail.
 */
export function GuestsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "competitions.manage", "members.manage")
  const guests = useQuery({ queryKey: guestKeys.list(orgId), queryFn: () => listGuests(orgId), enabled: allowed })
  const claims = useQuery({ queryKey: guestKeys.claims(orgId), queryFn: () => listGuestClaims(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(guests.error, claims.error)
  const all = allowed && !accessLost ? (guests.data?.results ?? []) : []
  const waiting = (claims.data?.results ?? []).filter((claim) => claim.status === "conflict")
  const settled = (claims.data?.results ?? []).filter((claim) => claim.status !== "conflict")

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Guests</h1>
        {active && <p className="text-muted-foreground">{active.organization.name}</p>}
      </div>
      <p className="text-muted-foreground">
        Players you enter before they have a Coast TT account. Invite them by email: when they accept with that address, their entries and matches become theirs. Names alone never join two
        players.
      </p>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          {waiting.length > 0 && (
            <section aria-labelledby="waiting-heading" className="flex flex-col gap-3">
              <h2 id="waiting-heading" className="flex items-center gap-2 text-xl font-bold">
                <TriangleAlert aria-hidden className="size-5 text-warning" /> Claims waiting for you
              </h2>
              {waiting.map((claim) => (
                <ClaimCard key={claim.id} orgId={orgId} claim={claim} />
              ))}
            </section>
          )}
          <NewGuest orgId={orgId} />
          {guests.isPending && <p className="text-muted-foreground">Loading guests…</p>}
          {guests.isError && <FormAlert>{errorMessage(guests.error, "We couldn't load the guests.")}</FormAlert>}
          {guests.isSuccess && all.length === 0 && <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">No guests yet.</p>}
          <ul className="flex flex-col gap-2">
            {all.map((guest) => (
              <GuestRow key={guest.id} orgId={orgId} guest={guest} />
            ))}
          </ul>
          {settled.length > 0 && (
            <section aria-labelledby="settled-heading" className="flex flex-col gap-3">
              <h2 id="settled-heading" className="text-xl font-bold">
                Past claims
              </h2>
              {settled.map((claim) => (
                <ClaimCard key={claim.id} orgId={orgId} claim={claim} />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  )
}

function NewGuest({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState("")
  const add = useMutation({
    mutationFn: () => createGuest(orgId, name.trim()),
    onSuccess: () => {
      setName("")
      void queryClient.invalidateQueries({ queryKey: guestKeys.all })
    },
  })
  const fields = add.error instanceof ApiError ? add.error.fieldErrors() : {}
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim()) add.mutate()
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-wrap items-end gap-3 rounded-xl border border-dashed p-4">
      <Field label="New guest's name" className="min-w-[220px] flex-1" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} error={fields.display_name} />
      <Button type="submit" disabled={add.isPending || !name.trim()}>
        <UserPlus aria-hidden className="size-5" /> Add guest
      </Button>
      {add.isError && !fields.display_name && <FormAlert>{errorMessage(add.error)}</FormAlert>}
    </form>
  )
}

function GuestRow({ orgId, guest }: { orgId: string; guest: Guest }) {
  const queryClient = useQueryClient()
  const [inviting, setInviting] = useState(false)
  const [email, setEmail] = useState("")
  const refresh = () => queryClient.invalidateQueries({ queryKey: guestKeys.all })
  const invite = useMutation({
    mutationFn: () => inviteGuest(orgId, guest.id, email.trim()),
    onSuccess: () => {
      setInviting(false)
      setEmail("")
      void refresh()
    },
  })
  const revoke = useMutation({ mutationFn: () => revokeGuestInvitation(orgId, guest.id), onSuccess: () => void refresh() })
  const fields = invite.error instanceof ApiError ? invite.error.fieldErrors() : {}
  const claimed = !!guest.claimed_at

  return (
    <li className={`${ROW} gap-y-2`}>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-semibold break-words">{guest.display_name}</span>
        <span className="text-sm text-muted-foreground">
          {claimed
            ? `Claimed by ${guest.claimed_by_name ?? "a player"} on ${when(guest.claimed_at!)}`
            : guest.invitation
              ? `Invited ${guest.invitation.email} · open until ${when(guest.invitation.expires_at)}`
              : `Added ${when(guest.created_at)} · not invited yet`}
          {!claimed && ` · ${guest.entries} ${guest.entries === 1 ? "entry" : "entries"}`}
        </span>
      </span>
      {!claimed && guest.invitation && (
        <Button variant="ghost" size="sm" disabled={revoke.isPending} onClick={() => revoke.mutate()} aria-label={`Withdraw the invitation for ${guest.display_name}`}>
          Withdraw invitation
        </Button>
      )}
      {!claimed && (
        <Button variant="outline" size="sm" aria-expanded={inviting} onClick={() => setInviting(!inviting)} aria-label={`Invite ${guest.display_name} to claim`}>
          <Mail aria-hidden className="size-4" /> {guest.invitation ? "Invite again" : "Invite"}
        </Button>
      )}
      {inviting && (
        <form
          noValidate
          className="flex basis-full flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            invite.mutate()
          }}
        >
          <Field label="Their email address" type="email" className="min-w-[220px] flex-1" value={email} onChange={(e) => setEmail(e.target.value)} error={fields.email} hint="They accept after signing in with this address." />
          <Button type="submit" disabled={invite.isPending || !email.trim()}>
            {invite.isPending ? "Sending…" : "Send invitation"}
          </Button>
        </form>
      )}
      {(revoke.isError || (invite.isError && !fields.email)) && (
        <div className="basis-full">
          <FormAlert>{errorMessage(revoke.error ?? invite.error)}</FormAlert>
        </div>
      )}
    </li>
  )
}

function ClaimCard({ orgId, claim }: { orgId: string; claim: GuestClaim }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState("")
  const settle = useMutation({
    mutationFn: (action: "retry" | "reject") => (action === "retry" ? retryGuestClaim : rejectGuestClaim)(orgId, claim.id, note.trim()),
    onSuccess: () => {
      setNote("")
      void queryClient.invalidateQueries({ queryKey: guestKeys.all })
    },
  })
  const open = claim.status === "conflict"
  return (
    <article className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <p>
        <span className="font-semibold">{claim.claimant_name}</span> accepted the invitation to {claim.invited_email} for the guest <span className="font-semibold">{claim.guest_name}</span>.
      </p>
      {open ? (
        <>
          <div className="rounded-lg border border-warning/40 bg-warning/5 p-3">
            <p className="font-semibold">Nothing has moved yet, because:</p>
            <ul className="list-disc pl-5">
              {claim.clashes.map((clash) => (
                <li key={clash}>{clash}</li>
              ))}
            </ul>
            <p className="mt-1 text-sm text-muted-foreground">Sort out the clash (for example, withdraw the duplicate entry), then try again. If they aren't the same player, reject the claim.</p>
          </div>
          <Field label="Note for the record" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} hint="Required: what you checked or changed." />
          <div className="flex flex-wrap gap-2">
            <Button disabled={!note.trim() || settle.isPending} onClick={() => settle.mutate("retry")}>
              Try again
            </Button>
            <Button variant="outline" disabled={!note.trim() || settle.isPending} onClick={() => settle.mutate("reject")}>
              Reject the claim
            </Button>
          </div>
          {settle.isError && <FormAlert>{errorMessage(settle.error)}</FormAlert>}
        </>
      ) : (
        <p className="text-sm font-semibold">{claim.status === "merged" ? "Merged into the player's account." : "Rejected: the guest stays as it was."}</p>
      )}
      <ol className="flex flex-col gap-1 border-t pt-2 text-sm text-muted-foreground" aria-label="What happened">
        {claim.events.map((event, index) => (
          <li key={index}>
            {when(event.at)} · {CLAIM_ACTION[event.action]}
            {event.actor_name && ` by ${event.actor_name}`}
            {event.note && `: ${event.note}`}
          </li>
        ))}
      </ol>
    </article>
  )
}
