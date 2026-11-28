import { useDeferredValue, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, UserRound } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { MemberFieldValuesForm } from "@/components/clubs/MemberFieldValuesForm"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import {
  assignHolder,
  clubKeys,
  createCommitteeField,
  createPosition,
  endHolder,
  FIELD_KIND_LABEL,
  getCommittee,
  listCommitteeCandidates,
  listCommitteeFields,
  listCommitteeHistory,
  listRoles,
  reorderPositions,
  retirePosition,
  savePositionValues,
  setCommitteeFieldRetired,
  updatePosition,
  useActiveMembership,
  withinAuthority,
  type Committee,
  type CommitteeField,
  type CommitteePosition,
  type FieldValue,
  type MemberFieldKind,
  type Membership,
  type PastHolder,
} from "@/lib/clubs"
import { OrganizationName } from "@/components/clubs/KindBadge"

const dateLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" })

const valueLabel = (value: FieldValue) => (typeof value === "boolean" ? (value ? "Yes" : "No") : String(value))

const END_REASON: Record<PastHolder["end_reason"], string> = {
  replaced: "replaced",
  stepped_down: "stepped down",
  left: "left the club",
  position_retired: "position removed",
}

function termLabel(position: CommitteePosition) {
  const { term_start: start, term_end: end } = position
  if (start && end) return `Term ${dateLabel(start)} to ${dateLabel(end)}`
  if (start) return `Term from ${dateLabel(start)}`
  if (end) return `Term until ${dateLabel(end)}`
  return null
}

/** The club's committee (REQ-045): every member sees who holds which position; governance staff set it up. */
export function CommitteePage() {
  const { memberships, active } = useActiveMembership()
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Committee</h1>
      {memberships.isPending && <p className="text-muted-foreground">Loading…</p>}
      {memberships.isSuccess && !active && <AccessLost />}
      {active && <CommitteeView key={active.organization.id} membership={active} />}
    </div>
  )
}

function CommitteeView({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const committee = useQuery({ queryKey: clubKeys.committee(orgId), queryFn: () => getCommittee(orgId) })
  const accessLost = useAdminAccessLost(committee.error)
  const manage = committee.data?.can_manage ?? false
  const positions = committee.data?.positions ?? []

  return (
    <>
      <p className="text-muted-foreground"><OrganizationName organization={membership.organization} /></p>
      {accessLost && <AccessLost />}
      {committee.isPending && <p className="text-muted-foreground">Loading the committee…</p>}
      {committee.isError && !accessLost && <FormAlert>{errorMessage(committee.error, "We couldn't load the committee.")}</FormAlert>}
      {committee.isSuccess && positions.length === 0 && (
        <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">
          {manage ? "No positions yet. Add the first one below, for example Chair." : "This club hasn't set up its committee yet."}
        </p>
      )}
      {positions.length > 0 && (
        <ol aria-label="Committee positions" className="flex flex-col gap-2">
          {positions.map((position, index) => (
            <PositionCard key={position.id} membership={membership} position={position} manage={manage} index={index} all={positions} />
          ))}
        </ol>
      )}
      {manage && <AddPosition orgId={orgId} />}
      <History orgId={orgId} />
      {manage && <CommitteeFields orgId={orgId} />}
    </>
  )
}

function useCommitteeUpdate(orgId: string) {
  const queryClient = useQueryClient()
  return async (committee: Committee) => {
    queryClient.setQueryData(clubKeys.committee(orgId), committee)
    // Holders and granted roles change permissions and the history.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: clubKeys.committeeHistory(orgId) }),
      queryClient.invalidateQueries({ queryKey: clubKeys.memberships }),
    ])
  }
}

function PositionCard({
  membership,
  position,
  manage,
  index,
  all,
}: {
  membership: Membership
  position: CommitteePosition
  manage: boolean
  index: number
  all: CommitteePosition[]
}) {
  const orgId = membership.organization.id
  const [editing, setEditing] = useState(false)
  const updated = useCommitteeUpdate(orgId)
  const move = useMutation({
    mutationFn: (to: number) => {
      const ids = all.map((p) => p.id)
      ids.splice(index, 1)
      ids.splice(to, 0, position.id)
      return reorderPositions(orgId, ids)
    },
    onSuccess: updated,
  })
  const values = [...position.values, ...(position.holder?.values ?? [])].filter((entry) => entry.value !== null)
  const term = termLabel(position)

  return (
    <li className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="text-lg font-bold">{position.name}</h2>
          <p className="flex items-center gap-2">
            <UserRound aria-hidden className="size-4 text-muted-foreground" />
            {position.holder ? (
              <span>
                <span className="font-semibold">{position.holder.display_name}</span>
                <span className="text-sm text-muted-foreground"> · since {dateLabel(position.holder.started_on)}</span>
              </span>
            ) : (
              <span className="text-muted-foreground">Vacant</span>
            )}
          </p>
          {term && <p className="text-sm text-muted-foreground">{term}</p>}
          {position.grants_role && <p className="text-sm text-brand-blue">Gives the holder the {position.grants_role.name} role</p>}
          {values.length > 0 && (
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              {values.map((entry) => (
                <div key={entry.field.id} className="contents">
                  <dt className="text-muted-foreground">{entry.field.label}</dt>
                  <dd>{valueLabel(entry.value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        {manage && (
          <div className="flex gap-1">
            <Button variant="ghost" size="icon" aria-label={`Move ${position.name} up`} disabled={index === 0 || move.isPending} onClick={() => move.mutate(index - 1)}>
              <ArrowUp aria-hidden className="size-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Move ${position.name} down`}
              disabled={index === all.length - 1 || move.isPending}
              onClick={() => move.mutate(index + 1)}
            >
              <ArrowDown aria-hidden className="size-5" />
            </Button>
            <Button variant="outline" aria-expanded={editing} onClick={() => setEditing(!editing)}>
              {editing ? "Close" : "Edit"}
            </Button>
          </div>
        )}
      </div>
      {move.isError && <FormAlert>{errorMessage(move.error)}</FormAlert>}
      {manage && editing && <PositionEditor membership={membership} position={position} onRetired={() => setEditing(false)} />}
    </li>
  )
}

function PositionEditor({ membership, position, onRetired }: { membership: Membership; position: CommitteePosition; onRetired: () => void }) {
  const orgId = membership.organization.id
  const updated = useCommitteeUpdate(orgId)
  const entries = [...position.values, ...(position.holder?.values ?? [])]
  const [confirmRetire, setConfirmRetire] = useState(false)
  const retire = useMutation({ mutationFn: () => retirePosition(orgId, position.id), onSuccess: async (c) => { await updated(c); onRetired() } })

  return (
    <div className="flex flex-col gap-5 border-t pt-4">
      <PositionDetails membership={membership} position={position} />
      <HolderEditor orgId={orgId} position={position} />
      {entries.length > 0 && (
        <section aria-label={`${position.name} details`} className="flex flex-col gap-2">
          <h3 className="font-bold">Committee details</h3>
          <MemberFieldValuesForm
            key={position.holder?.id ?? "vacant"}
            entries={entries}
            markStaffOnly
            submitLabel="Save committee details"
            save={(values) => savePositionValues(orgId, position.id, values)}
            onSaved={updated}
          />
        </section>
      )}
      <section aria-label={`Remove ${position.name}`} className="flex flex-col gap-2 border-t pt-4">
        {retire.isError && <FormAlert>{errorMessage(retire.error)}</FormAlert>}
        {confirmRetire ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="flex-1 text-sm">Remove {position.name}? Its holder's time ends and stays in the history.</p>
            <Button variant="outline" onClick={() => setConfirmRetire(false)}>
              Keep
            </Button>
            <Button variant="destructive" disabled={retire.isPending} onClick={() => retire.mutate()}>
              {retire.isPending ? "Removing…" : "Remove position"}
            </Button>
          </div>
        ) : (
          <Button variant="ghost" className="self-start text-destructive" onClick={() => setConfirmRetire(true)}>
            Remove position
          </Button>
        )}
      </section>
    </div>
  )
}

const NO_ROLE = "none"

function PositionDetails({ membership, position }: { membership: Membership; position: CommitteePosition }) {
  const orgId = membership.organization.id
  const updated = useCommitteeUpdate(orgId)
  const [name, setName] = useState(position.name)
  const [termStart, setTermStart] = useState(position.term_start ?? "")
  const [termEnd, setTermEnd] = useState(position.term_end ?? "")
  const [role, setRole] = useState(position.grants_role?.id ?? NO_ROLE)
  // Only people who can see the roles can pick one; the server checks the grant is within their authority.
  const roles = useQuery({ queryKey: clubKeys.roles(orgId), queryFn: () => listRoles(orgId), retry: false })
  const save = useMutation({
    mutationFn: () =>
      updatePosition(orgId, position.id, {
        name: name.trim(),
        term_start: termStart || null,
        term_end: termEnd || null,
        ...(roles.isSuccess ? { grants_role: role === NO_ROLE ? null : role } : {}),
      }),
    onSuccess: updated,
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const roleOptions = [
    { value: NO_ROLE, label: "No role" },
    ...(roles.data ?? [])
      .filter((r) => r.key !== "admin" && r.key !== "member")
      .map((r) => ({ value: r.id, label: r.name, disabled: !withinAuthority(membership, r.permissions) })),
  ]

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      <Field label="Position name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Term starts" optional type="date" value={termStart} onChange={(e) => setTermStart(e.target.value)} error={errors.term_start} />
        <Field label="Term ends" optional type="date" value={termEnd} onChange={(e) => setTermEnd(e.target.value)} error={errors.term_end} />
      </div>
      {roles.isSuccess && (
        <SelectField
          label="Role the holder gets"
          optional
          options={roleOptions}
          value={role}
          onChange={setRole}
          error={errors.grants_role}
          hint="Held only while they hold the position, e.g. Finance for the treasurer. Roles with permissions you don't hold can't be chosen."
        />
      )}
      {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      {save.isSuccess && !save.isPending && (
        <p role="status" className="text-sm text-success">
          Saved.
        </p>
      )}
      <Button type="submit" className="self-start" disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save position"}
      </Button>
    </form>
  )
}

function HolderEditor({ orgId, position }: { orgId: string; position: CommitteePosition }) {
  const updated = useCommitteeUpdate(orgId)
  const [term, setTerm] = useState("")
  const [startedOn, setStartedOn] = useState("")
  const search = useDeferredValue(term.trim())
  const candidates = useQuery({
    queryKey: clubKeys.committeeCandidates(orgId, search),
    queryFn: () => listCommitteeCandidates(orgId, search),
    enabled: search.length > 0,
  })
  const assign = useMutation({
    mutationFn: (membershipId: string) => assignHolder(orgId, position.id, membershipId, startedOn || undefined),
    onSuccess: async (c) => {
      setTerm("")
      await updated(c)
    },
  })
  const end = useMutation({ mutationFn: () => endHolder(orgId, position.id), onSuccess: updated })
  const holder = position.holder
  const results = (candidates.data?.results ?? []).filter((c) => c.id !== holder?.membership_id)

  return (
    <section aria-label={`Who holds ${position.name}`} className="flex flex-col gap-3">
      <h3 className="font-bold">Holder</h3>
      {holder && (
        <div className={ROW}>
          <span className="flex-1">
            <span className="font-semibold">{holder.display_name}</span>
            <span className="text-sm text-muted-foreground"> · since {dateLabel(holder.started_on)}</span>
          </span>
          <Button variant="outline" disabled={end.isPending} onClick={() => end.mutate()}>
            {end.isPending ? "Ending…" : "End their time"}
          </Button>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label={holder ? "Replace with" : "Find a member"}
          type="search"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          hint="Active members of the club, by display name"
        />
        <Field label="Started on" optional type="date" value={startedOn} onChange={(e) => setStartedOn(e.target.value)} hint="Today if left blank" />
      </div>
      {candidates.isError && <FormAlert>{errorMessage(candidates.error, "We couldn't search members.")}</FormAlert>}
      {search && candidates.isSuccess && results.length === 0 && <p className="text-sm text-muted-foreground">No members match.</p>}
      {results.length > 0 && (
        <ul aria-label="Matching members" className="flex flex-col gap-2">
          {results.map((candidate) => (
            <li key={candidate.id} className={ROW}>
              <span className="flex-1 font-semibold">{candidate.display_name || "Unnamed player"}</span>
              <Button
                disabled={assign.isPending}
                aria-label={`Make ${candidate.display_name || "this member"} ${position.name.toLowerCase()}`}
                onClick={() => assign.mutate(candidate.id)}
              >
                Make {position.name.toLowerCase()}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {assign.isError && <FormAlert>{errorMessage(assign.error)}</FormAlert>}
      {end.isError && <FormAlert>{errorMessage(end.error)}</FormAlert>}
    </section>
  )
}

function AddPosition({ orgId }: { orgId: string }) {
  const updated = useCommitteeUpdate(orgId)
  const [name, setName] = useState("")
  const add = useMutation({
    mutationFn: () => createPosition(orgId, { name: name.trim() }),
    onSuccess: async (c) => {
      setName("")
      await updated(c)
    },
  })
  const errors = add.error instanceof ApiError ? add.error.fieldErrors() : {}
  return (
    <form
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        add.mutate()
      }}
    >
      <Field label="Add a position" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} hint="For example Chair, Secretary, Treasurer or Youth officer" />
      {add.isError && !errors.name && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <Button type="submit" className="self-start" disabled={add.isPending || !name.trim()}>
        {add.isPending ? "Adding…" : "Add position"}
      </Button>
    </form>
  )
}

function History({ orgId }: { orgId: string }) {
  const history = useQuery({ queryKey: clubKeys.committeeHistory(orgId), queryFn: () => listCommitteeHistory(orgId) })
  const items = history.data?.results ?? []
  if (history.isError) return <FormAlert>{errorMessage(history.error, "We couldn't load the committee history.")}</FormAlert>
  if (!items.length) return null
  return (
    <section aria-labelledby="committee-history-heading" className="flex flex-col gap-3">
      <h2 id="committee-history-heading" className="text-xl font-bold">
        Past holders
      </h2>
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.id} className="text-sm">
            <span className="font-semibold">{item.display_name}</span>, {item.position}, {dateLabel(item.started_on)} to {dateLabel(item.ended_on)}
            <span className="text-muted-foreground"> ({END_REASON[item.end_reason]})</span>
          </li>
        ))}
      </ul>
      {history.data && history.data.count > items.length && (
        <p className="text-sm text-muted-foreground">
          Showing the latest {items.length} of {history.data.count}.
        </p>
      )}
    </section>
  )
}

const KIND_OPTIONS = (Object.keys(FIELD_KIND_LABEL) as MemberFieldKind[]).map((kind) => ({ value: kind, label: FIELD_KIND_LABEL[kind] }))
const APPLIES_OPTIONS: { value: CommitteeField["applies_to"]; label: string; description: string }[] = [
  { value: "position", label: "The position", description: "e.g. the portfolio it covers" },
  { value: "holder", label: "The holder", description: "e.g. how they were elected; starts blank for each new holder" },
]
const VISIBILITY_OPTIONS: { value: CommitteeField["visibility"]; label: string; description: string }[] = [
  { value: "member", label: "Every member", description: "Shown with the committee" },
  { value: "staff", label: "Committee managers", description: "Only people who set the committee" },
]

/** Custom committee fields (REQ-045), per position or per holder. */
function CommitteeFields({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const fields = useQuery({ queryKey: clubKeys.committeeFields(orgId), queryFn: () => listCommitteeFields(orgId) })
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: clubKeys.committeeFields(orgId) }),
      queryClient.invalidateQueries({ queryKey: clubKeys.committee(orgId), exact: true }),
    ])
  const toggle = useMutation({
    mutationFn: (field: CommitteeField) => setCommitteeFieldRetired(orgId, field.id, !field.retired_at),
    onSettled: refresh,
  })
  const [label, setLabel] = useState("")
  const [kind, setKind] = useState<MemberFieldKind | "">("")
  const [options, setOptions] = useState("")
  const [appliesTo, setAppliesTo] = useState<CommitteeField["applies_to"]>("position")
  const [visibility, setVisibility] = useState<CommitteeField["visibility"]>("member")
  const create = useMutation({
    mutationFn: () =>
      createCommitteeField(orgId, {
        label: label.trim(),
        kind: (kind || undefined) as MemberFieldKind,
        applies_to: appliesTo,
        visibility,
        ...(kind === "choice" ? { options: options.split("\n").map((o) => o.trim()).filter(Boolean) } : {}),
      }),
    onSuccess: async () => {
      setLabel("")
      setKind("")
      setOptions("")
      await refresh()
    },
  })
  const errors = create.error instanceof ApiError ? create.error.fieldErrors() : {}

  return (
    <section aria-labelledby="committee-fields-heading" className="flex flex-col gap-3 border-t pt-6">
      <h2 id="committee-fields-heading" className="text-xl font-bold">
        Committee fields
      </h2>
      <p className="text-sm text-muted-foreground">Extra details kept for each position or its holder. Fill them in under Edit on a position.</p>
      {fields.isError && <FormAlert>{errorMessage(fields.error, "We couldn't load committee fields.")}</FormAlert>}
      {toggle.isError && <FormAlert>{errorMessage(toggle.error)}</FormAlert>}
      {(fields.data ?? []).length > 0 && (
        <ul aria-label="Committee fields" className="flex flex-col gap-2">
          {fields.data!.map((field) => (
            <li key={field.id} className={ROW}>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold">
                  {field.label}
                  {field.retired_at && <span className="font-normal text-muted-foreground"> · retired</span>}
                </span>
                <span className="text-sm text-muted-foreground">
                  {FIELD_KIND_LABEL[field.kind]} · about the {field.applies_to} · {field.visibility === "member" ? "every member sees it" : "committee managers only"}
                </span>
              </span>
              <Button variant="outline" disabled={toggle.isPending && toggle.variables?.id === field.id} onClick={() => toggle.mutate(field)}>
                {field.retired_at ? "Restore" : "Retire"}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-col gap-4 rounded-xl border bg-card p-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate()
        }}
      >
        <Field label="New field label" maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} error={errors.label} hint="e.g. Portfolio or Elected at" />
        <ChoiceGroup legend="Type" columns={3} options={KIND_OPTIONS} value={kind} onChange={setKind} error={errors.kind} />
        {kind === "choice" && (
          <TextAreaField label="Options" rows={4} value={options} onChange={(e) => setOptions(e.target.value)} error={errors.options} hint="One per line, at least two." />
        )}
        <ChoiceGroup legend="Describes" options={APPLIES_OPTIONS} value={appliesTo} onChange={setAppliesTo} error={errors.applies_to} />
        <ChoiceGroup legend="Who sees it" options={VISIBILITY_OPTIONS} value={visibility} onChange={setVisibility} error={errors.visibility} />
        {create.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(create.error)}</FormAlert>}
        <Button type="submit" className="self-start" disabled={create.isPending}>
          {create.isPending ? "Adding…" : "Add field"}
        </Button>
      </form>
    </section>
  )
}
