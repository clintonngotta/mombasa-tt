import { useDeferredValue, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { errorMessage } from "@/lib/api"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { clubKeys, isBodyKind, listCommitteeCandidates, useActiveMembership, type Membership } from "@/lib/clubs"
import {
  decideRepresentative,
  getRepresentatives,
  isOpen,
  nominateRepresentative,
  representativeKeys,
  setRepresentativeCap,
  statusLabel,
  termLabel,
  withdrawRepresentative,
  type Representative,
  type Representatives,
} from "@/lib/representatives"

/** Representatives (REQ-045): who a club sends to its region's body (or a region to the national body),
 * and for a body, who is sent to it. Members read it; governance staff nominate, decide and set the limit. */
export function RepresentativesPage() {
  const { memberships, active } = useActiveMembership()
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">{active?.organization.name ?? "Club"}</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Representatives</h1>
      {memberships.isPending && <p className="text-muted-foreground">Loading…</p>}
      {memberships.isSuccess && !active && <AccessLost />}
      {active && <RepresentativesView key={active.organization.id} membership={active} />}
    </div>
  )
}

function useRefresh(orgId: string) {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: representativeKeys.list(orgId) })
}

function RepresentativesView({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const body = isBodyKind(membership.organization.kind)
  // The other side decides, so a saved copy is checked against the server each time the page opens.
  const list = useQuery({ queryKey: representativeKeys.list(orgId), queryFn: () => getRepresentatives(orgId), staleTime: 0 })
  const accessLost = useAdminAccessLost(list.error)

  if (accessLost) return <AccessLost />
  if (list.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (list.isError) return <FormAlert>{errorMessage(list.error, "We couldn't load the representatives.")}</FormAlert>
  const data = list.data
  const sends = membership.organization.kind !== "national_body" && membership.organization.kind !== "facility" && membership.organization.kind !== "coaching"

  return (
    <>
      {data.receives && <Received orgId={orgId} data={data} />}
      {sends && <Sent orgId={orgId} data={data} body={body} />}
    </>
  )
}

function Row({ representative, who, children }: { representative: Representative; who: string; children?: React.ReactNode }) {
  const term = termLabel(representative)
  return (
    <li className={ROW}>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-semibold">{representative.person.display_name || "Unnamed player"}</span>
        <span className="text-sm text-muted-foreground">
          {who} · {statusLabel(representative)}
          {term && ` · ${term}`}
        </span>
        {representative.note && <span className="text-sm text-muted-foreground">Note from the body: {representative.note}</span>}
      </span>
      {children}
    </li>
  )
}

/** What this organization sends up: its current representatives, nominations and, for staff, the form. */
function Sent({ orgId, data, body }: { orgId: string; data: Representatives; body: boolean }) {
  const refresh = useRefresh(orgId)
  const withdraw = useMutation({ mutationFn: (id: string) => withdrawRepresentative(orgId, id), onSuccess: refresh })
  const [replacing, setReplacing] = useState<Representative | null>(null)
  const open = data.sent.filter(isOpen)
  const closed = data.sent.filter((r) => !isOpen(r))
  const places = open.filter((r) => r.status === "pending" || r.in_term).length
  const full = data.cap !== null && places >= data.cap

  return (
    <section aria-labelledby="sent-heading" className="flex flex-col gap-3">
      <h2 id="sent-heading" className="text-xl font-bold">
        {data.body ? `Sent to ${data.body.name}` : "Sent to the governing body"}
      </h2>
      {!data.body && (
        <p className="text-muted-foreground">
          {body ? "The national body hasn't been set up yet." : "Your region has no governing body yet, or the club's country and region aren't set in its profile."}
        </p>
      )}
      {data.body && (
        <p className="text-sm text-muted-foreground">
          {data.cap === null ? `${data.body.name} sets no limit on representatives.` : `${data.body.name} takes at most ${data.cap} from each organization. ${places} of ${data.cap} used.`}{" "}
          They see each representative's name and who they speak for, nothing else.
        </p>
      )}
      {data.body && open.length === 0 && <p className="text-muted-foreground">Nobody represents you there yet.</p>}
      <ul aria-label="Representatives and nominations" className="flex flex-col gap-2">
        {open.map((representative) => (
          <Row key={representative.id} representative={representative} who={`To ${representative.body.name}`}>
            {data.can_manage && (
              <span className="flex flex-wrap gap-2">
                {representative.status === "accepted" && (
                  <Button variant="outline" aria-label={`Replace ${representative.person.display_name}`} onClick={() => setReplacing(representative)}>
                    Replace
                  </Button>
                )}
                <Button
                  variant="outline"
                  disabled={withdraw.isPending}
                  aria-label={`${representative.status === "pending" ? "Withdraw the nomination of" : "Recall"} ${representative.person.display_name}`}
                  onClick={() => withdraw.mutate(representative.id)}
                >
                  {representative.status === "pending" ? "Withdraw" : "Recall"}
                </Button>
              </span>
            )}
          </Row>
        ))}
      </ul>
      {withdraw.isError && <FormAlert>{errorMessage(withdraw.error)}</FormAlert>}
      {data.can_manage && data.body && (
        <Nominate key={replacing?.id ?? "new"} orgId={orgId} replacing={replacing} full={full && !replacing} onDone={() => setReplacing(null)} />
      )}
      {closed.length > 0 && <Earlier rows={closed} who={(r) => `To ${r.body.name}`} />}
    </section>
  )
}

function Nominate({ orgId, replacing, full, onDone }: { orgId: string; replacing: Representative | null; full: boolean; onDone: () => void }) {
  const refresh = useRefresh(orgId)
  const [term, setTerm] = useState("")
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")
  const search = useDeferredValue(term.trim())
  const candidates = useQuery({
    queryKey: clubKeys.committeeCandidates(orgId, search),
    queryFn: () => listCommitteeCandidates(orgId, search),
    enabled: search.length > 0,
  })
  const nominate = useMutation({
    mutationFn: (membershipId: string) =>
      nominateRepresentative(orgId, { membership_id: membershipId, term_start: start || null, term_end: end || null, replaces: replacing?.id ?? null }),
    onSuccess: async () => {
      setTerm("")
      onDone()
      await refresh()
    },
  })
  const results = candidates.data?.results ?? []

  if (full) return <p className="text-sm text-muted-foreground">Every place is taken. Replace or recall a representative to send somebody else.</p>
  return (
    <section aria-label={replacing ? `Replace ${replacing.person.display_name}` : "Nominate a representative"} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h3 className="font-bold">{replacing ? `Replace ${replacing.person.display_name}` : "Nominate a representative"}</h3>
      {replacing && (
        <p className="text-sm text-muted-foreground">
          {replacing.person.display_name} stays until the body accepts the new nomination.{" "}
          <button type="button" className="font-semibold underline" onClick={onDone}>
            Cancel
          </button>
        </p>
      )}
      <Field label="Find a member" type="search" value={term} onChange={(e) => setTerm(e.target.value)} hint="Active members, by display name" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Term starts" optional type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        <Field label="Term ends" optional type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} />
      </div>
      {candidates.isError && <FormAlert>{errorMessage(candidates.error, "We couldn't search members.")}</FormAlert>}
      {search && candidates.isSuccess && results.length === 0 && <p className="text-sm text-muted-foreground">No members match.</p>}
      {results.length > 0 && (
        <ul aria-label="Matching members" className="flex flex-col gap-2">
          {results.map((candidate) => (
            <li key={candidate.id} className={ROW}>
              <span className="flex-1 font-semibold">{candidate.display_name || "Unnamed player"}</span>
              <Button disabled={nominate.isPending} aria-label={`Nominate ${candidate.display_name || "this member"}`} onClick={() => nominate.mutate(candidate.id)}>
                Nominate
              </Button>
            </li>
          ))}
        </ul>
      )}
      {nominate.isError && <FormAlert>{errorMessage(nominate.error)}</FormAlert>}
    </section>
  )
}

/** A governing body's side: nominations to decide, current representatives by organization, and the limit. */
function Received({ orgId, data }: { orgId: string; data: Representatives }) {
  const refresh = useRefresh(orgId)
  const [noteFor, setNoteFor] = useState<{ representative: Representative; action: "decline" | "remove" } | null>(null)
  const [note, setNote] = useState("")
  const decide = useMutation({
    mutationFn: ({ id, action, text }: { id: string; action: "accept" | "decline" | "remove"; text?: string }) => decideRepresentative(orgId, id, action, text),
    onSuccess: async () => {
      setNoteFor(null)
      setNote("")
      await refresh()
    },
  })
  const pending = data.received.filter((r) => r.status === "pending")
  const current = data.received.filter((r) => r.status === "accepted")
  const closed = data.received.filter((r) => !isOpen(r))

  function submitNote(event: FormEvent) {
    event.preventDefault()
    if (noteFor) decide.mutate({ id: noteFor.representative.id, action: noteFor.action, text: note.trim() })
  }

  return (
    <section aria-labelledby="received-heading" className="flex flex-col gap-3">
      <h2 id="received-heading" className="text-xl font-bold">
        Representatives here
      </h2>
      <p className="text-sm text-muted-foreground">
        You see each representative's name and the organization they speak for. They are not members here and hold no role.
      </p>
      {data.can_manage && <Cap orgId={orgId} cap={data.own_cap} />}
      {!data.can_manage && data.own_cap !== null && <p className="text-sm text-muted-foreground">At most {data.own_cap} from each organization.</p>}

      {data.can_manage && (
        <>
          <h3 className="font-bold">Nominations to decide</h3>
          {pending.length === 0 && <p className="text-muted-foreground">Nothing is waiting.</p>}
          <ul aria-label="Nominations to decide" className="flex flex-col gap-2">
            {pending.map((representative) => (
              <Row key={representative.id} representative={representative} who={representative.sender.name}>
                <span className="flex flex-wrap gap-2">
                  <Button
                    disabled={decide.isPending}
                    aria-label={`Accept ${representative.person.display_name} for ${representative.sender.name}`}
                    onClick={() => decide.mutate({ id: representative.id, action: "accept" })}
                  >
                    Accept
                  </Button>
                  <Button
                    variant="outline"
                    disabled={decide.isPending}
                    aria-label={`Decline ${representative.person.display_name} for ${representative.sender.name}`}
                    onClick={() => setNoteFor({ representative, action: "decline" })}
                  >
                    Decline
                  </Button>
                </span>
              </Row>
            ))}
          </ul>
        </>
      )}

      <h3 className="font-bold">Current representatives</h3>
      {current.length === 0 && <p className="text-muted-foreground">No representatives yet.</p>}
      <ul aria-label="Current representatives" className="flex flex-col gap-2">
        {current.map((representative) => (
          <Row key={representative.id} representative={representative} who={representative.sender.name}>
            {data.can_manage && (
              <Button variant="outline" aria-label={`Remove ${representative.person.display_name}`} onClick={() => setNoteFor({ representative, action: "remove" })}>
                Remove
              </Button>
            )}
          </Row>
        ))}
      </ul>

      {noteFor && (
        <form onSubmit={submitNote} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
          <h3 className="font-bold">
            {noteFor.action === "decline" ? "Decline" : "Remove"} {noteFor.representative.person.display_name} ({noteFor.representative.sender.name})
          </h3>
          <Field label="Note to the sender" optional maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex gap-2">
            <Button type="submit" disabled={decide.isPending}>
              {noteFor.action === "decline" ? "Decline the nomination" : "Remove the representative"}
            </Button>
            <Button type="button" variant="outline" onClick={() => setNoteFor(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {decide.isError && <FormAlert>{errorMessage(decide.error)}</FormAlert>}
      {closed.length > 0 && <Earlier rows={closed} who={(r) => r.sender.name} />}
    </section>
  )
}

function Cap({ orgId, cap }: { orgId: string; cap: number | null }) {
  const refresh = useRefresh(orgId)
  const [value, setValue] = useState(cap === null ? "" : String(cap))
  const save = useMutation({ mutationFn: () => setRepresentativeCap(orgId, value === "" ? null : Number(value)), onSuccess: refresh })
  const changed = value !== (cap === null ? "" : String(cap))

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate()
      }}
      className="flex flex-wrap items-end gap-3"
    >
      <Field
        label="Limit per organization"
        optional
        type="number"
        min={1}
        max={20}
        inputMode="numeric"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        hint="Leave empty for no limit"
        className="w-64"
      />
      <Button type="submit" variant="outline" disabled={!changed || save.isPending}>
        {save.isPending ? "Saving…" : "Save limit"}
      </Button>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
    </form>
  )
}

function Earlier({ rows, who }: { rows: Representative[]; who: (representative: Representative) => string }) {
  return (
    <details className="rounded-xl border bg-card p-4">
      <summary className="cursor-pointer font-semibold">Earlier ({rows.length})</summary>
      <ul className="mt-3 flex flex-col gap-2">
        {rows.map((representative) => (
          <Row key={representative.id} representative={representative} who={who(representative)} />
        ))}
      </ul>
    </details>
  )
}
