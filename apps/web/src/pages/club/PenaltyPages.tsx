import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Gavel, Search } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { formatDay } from "@/lib/dates"
import { toMinor } from "@/lib/finance"
import {
  ABSENCE_LABEL,
  ABSENCES,
  appealPenalty,
  decideAppeal,
  describePenalty,
  getAbsenceRules,
  issuePenalty,
  KIND_LABEL,
  listMyPenalties,
  listPenalties,
  penaltyKeys,
  proposePenalties,
  saveAbsenceRules,
  waivePenalty,
  type Absence,
  type AbsencePenalty,
  type AbsenceRule,
  type MyAbsencePenalty,
  type PenaltyKind,
} from "@/lib/penalties"

type RuleDraft = { on: boolean; kind: PenaltyKind; events: string; points: string; fine: string; excuses: boolean }
const blank: RuleDraft = { on: false, kind: "warning", events: "1", points: "1", fine: "", excuses: true }
const fromRule = (rule?: AbsenceRule): RuleDraft =>
  rule ? { on: rule.active ?? true, kind: rule.kind ?? "warning", events: String(rule.suspension_events ?? 1), points: String(rule.points ?? 1), fine: rule.fine_minor ? String(rule.fine_minor / 100) : "", excuses: rule.apology_excuses ?? true } : blank

/** Absence penalties for governance staff (REQ-054): the rules, looking for absences, and deciding each
 * proposed penalty and each appeal. */
export function PenaltiesPage() {
  const { active } = useActiveMembership()
  const queryClient = useQueryClient()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "governance.manage")
  const rules = useQuery({ queryKey: penaltyKeys.rules(orgId), queryFn: () => getAbsenceRules(orgId), enabled: allowed })
  // Members appeal while staff look, so read the list fresh each time.
  const list = useQuery({ queryKey: penaltyKeys.list(orgId), queryFn: () => listPenalties(orgId), enabled: allowed, staleTime: 0 })
  const look = useMutation({ mutationFn: () => proposePenalties(orgId), onSuccess: () => queryClient.invalidateQueries({ queryKey: penaltyKeys.list(orgId) }) })
  const proposed = (list.data ?? []).filter((p) => p.status === "proposed")
  const appeals = (list.data ?? []).filter((p) => p.appeal === "pending")
  const decided = (list.data ?? []).filter((p) => p.status !== "proposed" && p.appeal !== "pending")

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">{active?.organization.name ?? "Club"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Absence penalties</h1>
        <p className="text-muted-foreground">For members who miss what they signed up or were picked for. Meetings have their own rules.</p>
      </div>
      {!allowed && <FormAlert>Penalties are set and decided by governance staff.</FormAlert>}
      {allowed && rules.data && <Rules orgId={orgId} rules={rules.data} canFine={can(active, "finances.manage")} />}
      {allowed && (
        <section aria-labelledby="proposed-heading" className="flex flex-col gap-3">
          <h2 id="proposed-heading" className="text-xl font-bold">
            To decide
          </h2>
          <p className="text-muted-foreground">The app proposes; nothing reaches a member until you issue it.</p>
          <Button variant="outline" className="self-start" disabled={look.isPending} onClick={() => look.mutate()}>
            <Search aria-hidden className="size-4" /> {look.isPending ? "Looking…" : "Look for absences in the last 90 days"}
          </Button>
          {look.isSuccess && (
            <p role="status" className="text-sm font-semibold">
              {look.data.proposed === 0 ? "Nothing new found." : `${look.data.proposed} new ${look.data.proposed === 1 ? "penalty" : "penalties"} proposed.`}
            </p>
          )}
          {(look.error ?? list.error) && <FormAlert>{errorMessage(look.error ?? list.error)}</FormAlert>}
          {list.isSuccess && proposed.length === 0 && <p className="text-muted-foreground">Nothing waiting.</p>}
          <ul className="flex flex-col gap-2">
            {proposed.map((penalty) => (
              <Decide key={penalty.id} orgId={orgId} penalty={penalty} />
            ))}
          </ul>
        </section>
      )}
      {allowed && appeals.length > 0 && (
        <section aria-labelledby="appeals-heading" className="flex flex-col gap-3">
          <h2 id="appeals-heading" className="text-xl font-bold">
            Appeals
          </h2>
          <ul className="flex flex-col gap-2">
            {appeals.map((penalty) => (
              <Appeal key={penalty.id} orgId={orgId} penalty={penalty} />
            ))}
          </ul>
        </section>
      )}
      {allowed && decided.length > 0 && (
        <section aria-labelledby="decided-heading" className="flex flex-col gap-3">
          <h2 id="decided-heading" className="text-xl font-bold">
            Decided
          </h2>
          <ul className="flex flex-col gap-2">
            {decided.map((penalty) => (
              <li key={penalty.id} className="rounded-lg border bg-card px-3 py-2">
                <PenaltyText penalty={penalty} />
                <p className="text-sm text-muted-foreground">
                  {penalty.status === "issued" ? "Issued" : "Waived"}
                  {penalty.decided_by_name && ` by ${penalty.decided_by_name}`}
                  {penalty.reason && `: ${penalty.reason}`}
                  {penalty.appeal === "rejected" && " · appeal turned down"}
                  {penalty.appeal === "upheld" && " · appeal upheld"}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function PenaltyText({ penalty }: { penalty: AbsencePenalty }) {
  return (
    <>
      <p className="font-semibold">
        {penalty.member_name} <span className="font-normal text-muted-foreground">· {penalty.what}</span>
      </p>
      <p className="text-sm">
        {ABSENCE_LABEL[penalty.applies_to]} on {formatDay(penalty.happened_on)} · {describePenalty(penalty)}
      </p>
    </>
  )
}

function Decide({ orgId, penalty }: { orgId: string; penalty: AbsencePenalty }) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState("")
  const done = () => queryClient.invalidateQueries({ queryKey: penaltyKeys.list(orgId) })
  const issue = useMutation({ mutationFn: () => issuePenalty(orgId, penalty.id, reason.trim()), onSuccess: done })
  const waive = useMutation({ mutationFn: () => waivePenalty(orgId, penalty.id, reason.trim()), onSuccess: done })
  const failed = issue.error ?? waive.error
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <PenaltyText penalty={penalty} />
      {failed && <FormAlert>{errorMessage(failed)}</FormAlert>}
      <Field label={`Reason for ${penalty.member_name}`} optional maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Needed to waive. The member sees it." />
      <div className="flex flex-wrap gap-2">
        <Button disabled={issue.isPending || waive.isPending} onClick={() => issue.mutate()}>
          <Gavel aria-hidden className="size-4" /> Issue
        </Button>
        <Button variant="outline" disabled={!reason.trim() || issue.isPending || waive.isPending} onClick={() => waive.mutate()}>
          Waive
        </Button>
      </div>
    </li>
  )
}

function Appeal({ orgId, penalty }: { orgId: string; penalty: AbsencePenalty }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState("")
  const decide = useMutation({ mutationFn: (upheld: boolean) => decideAppeal(orgId, penalty.id, upheld, note.trim()), onSuccess: () => queryClient.invalidateQueries({ queryKey: penaltyKeys.list(orgId) }) })
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <PenaltyText penalty={penalty} />
      <p className="rounded-lg border px-3 py-2 whitespace-pre-wrap">{penalty.appeal_text}</p>
      {decide.isError && <FormAlert>{errorMessage(decide.error)}</FormAlert>}
      <Field label={`Answer to ${penalty.member_name}`} optional maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button disabled={decide.isPending} onClick={() => decide.mutate(true)}>
          Uphold the appeal and waive
        </Button>
        <Button variant="outline" disabled={decide.isPending} onClick={() => decide.mutate(false)}>
          Turn it down
        </Button>
      </div>
    </li>
  )
}

function Rules({ orgId, rules, canFine }: { orgId: string; rules: AbsenceRule[]; canFine: boolean }) {
  const queryClient = useQueryClient()
  const draft = useDraft(`absence-rules:${orgId}`)
  const [drafts, setDrafts] = useDraftState<Record<Absence, RuleDraft>>(draft, "drafts", () => Object.fromEntries(ABSENCES.map((kind) => [kind, fromRule(rules.find((rule) => rule.applies_to === kind))])) as Record<Absence, RuleDraft>)
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () =>
      saveAbsenceRules(
        orgId,
        ABSENCES.filter((kind) => drafts[kind].on).map((kind) => {
          const d = drafts[kind]
          return { applies_to: kind, kind: d.kind, suspension_events: d.kind === "suspension" ? Number(d.events) || 1 : null, points: d.kind === "points" ? Number(d.points) || 1 : null, fine_minor: toMinor(d.fine), apology_excuses: d.excuses }
        })
      ),
    onSuccess: (fresh) => {
      draft.clear()
      queryClient.setQueryData(penaltyKeys.rules(orgId), fresh)
      setSaved(true)
    },
  })
  const set = (kind: Absence, change: Partial<RuleDraft>) => {
    setSaved(false)
    setDrafts({ ...drafts, [kind]: { ...drafts[kind], ...change } })
  }
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-4 rounded-xl border bg-card p-4"
    >
      <h2 className="text-xl font-bold">Rules</h2>
      {ABSENCES.map((kind) => {
        const d = drafts[kind]
        return (
          <fieldset key={kind} className="flex flex-col gap-3 rounded-lg border p-3">
            <legend className="px-1 font-semibold">{ABSENCE_LABEL[kind]}</legend>
            <label className="flex min-h-12 items-center gap-3">
              <input type="checkbox" className="size-5 accent-brand-blue" checked={d.on} onChange={(e) => set(kind, { on: e.target.checked })} />
              Propose a penalty for this
            </label>
            {d.on && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <SelectField label="Penalty" options={(Object.keys(KIND_LABEL) as PenaltyKind[]).map((value) => ({ value, label: KIND_LABEL[value] }))} value={d.kind} onChange={(value) => set(kind, { kind: value as PenaltyKind })} />
                  {d.kind === "suspension" && <Field label="For how many squads" type="number" min={1} max={20} inputMode="numeric" value={d.events} onChange={(e) => set(kind, { events: e.target.value })} hint="Left out of the rotation until that many squads are published." />}
                  {d.kind === "points" && <Field label="Points" type="number" min={1} max={100} inputMode="numeric" value={d.points} onChange={(e) => set(kind, { points: e.target.value })} />}
                </div>
                <Field label="Fine (KES)" optional inputMode="decimal" className="max-w-xs" disabled={!canFine} value={d.fine} onChange={(e) => set(kind, { fine: e.target.value })} hint={canFine ? "Charged to the member when the penalty is issued. Coast TT doesn't collect it." : "Setting a fine takes the finance permission."} />
                {kind === "training" && (
                  <label className="flex min-h-12 items-center gap-3">
                    <input type="checkbox" className="size-5 accent-brand-blue" checked={d.excuses} onChange={(e) => set(kind, { excuses: e.target.checked })} />
                    An apology sent before the start excuses the absence
                  </label>
                )}
              </>
            )}
          </fieldset>
        )
      })}
      {save.isError && <FormAlert>{fields.rules ?? errorMessage(save.error, "We couldn't save the rules.")}</FormAlert>}
      <DraftBar draft={draft} />
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save rules"}
        </Button>
        {saved && (
          <span role="status" className="text-sm font-semibold text-muted-foreground">
            Saved
          </span>
        )}
      </div>
    </form>
  )
}

const MY_STATUS: Record<MyAbsencePenalty["status"], string> = { proposed: "Proposed", issued: "Issued", waived: "Waived" }

function MyPenalty({ penalty }: { penalty: MyAbsencePenalty }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")
  const appeal = useMutation({
    mutationFn: () => appealPenalty(penalty.id, text.trim()),
    onSuccess: () => {
      setOpen(false)
      return queryClient.invalidateQueries({ queryKey: penaltyKeys.mine })
    },
  })
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {penalty.what} <span className="font-normal text-muted-foreground">· {penalty.organization_name}</span>
      </p>
      <p className="text-sm">
        {ABSENCE_LABEL[penalty.applies_to]} on {formatDay(penalty.happened_on)} · {describePenalty(penalty)}
      </p>
      <p className="text-sm text-muted-foreground">
        {MY_STATUS[penalty.status]}
        {penalty.reason && `: ${penalty.reason}`}
        {penalty.appeal === "pending" && " · your appeal is waiting for an answer"}
        {penalty.appeal === "rejected" && ` · your appeal was turned down${penalty.appeal_note ? `: ${penalty.appeal_note}` : ""}`}
        {penalty.appeal === "upheld" && " · your appeal succeeded"}
      </p>
      {penalty.status === "issued" && !!penalty.fine_minor && <p className="text-sm">The fine is on your club account. Pay the treasurer; Coast TT doesn't take payments.</p>}
      {penalty.can_appeal && !open && (
        <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
          Appeal
        </Button>
      )}
      {open && (
        <div className="flex flex-col gap-2">
          <TextAreaField label="Why is this penalty wrong?" rows={3} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} hint="You can appeal a penalty once." />
          {appeal.isError && <FormAlert>{errorMessage(appeal.error)}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button disabled={!text.trim() || appeal.isPending} onClick={() => appeal.mutate()}>
              {appeal.isPending ? "Sending…" : "Send appeal"}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}

/** Penalties issued to you for absences, in every club, and appealing one. Only you see this list. */
export function MyPenaltiesPage() {
  // Staff issue and answer appeals while you aren't looking, so ask the server each time.
  const mine = useQuery({ queryKey: penaltyKeys.mine, queryFn: listMyPenalties, staleTime: 0 })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/home">Home</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">My penalties</h1>
        <p className="text-muted-foreground">For absences from training, tournaments or squads. Only you and your club's officials see them.</p>
      </div>
      {mine.isError && <FormAlert>{errorMessage(mine.error, "We couldn't load your penalties.")}</FormAlert>}
      {mine.isSuccess && mine.data.length === 0 && <p className="text-muted-foreground">You have no penalties.</p>}
      <ul className="flex flex-col gap-2">
        {mine.data?.map((penalty) => (
          <MyPenalty key={penalty.id} penalty={penalty} />
        ))}
      </ul>
    </div>
  )
}
