import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { formatMoney } from "@/lib/coaching"
import { formatDay } from "@/lib/dates"
import {
  addExternalSource,
  deleteExternalSource,
  externalKeys,
  getIncomeTotals,
  listExternalIncome,
  listExternalSources,
  recordExternalIncome,
  reverseExternalIncome,
  setExternalSourceActive,
  toMinor,
  type ExternalIncome,
  type ExternalSource,
} from "@/lib/finance"
import { cn } from "@/lib/utils"

const today = () => new Date().toISOString().slice(0, 10)

/** Money from outside the membership (REQ-051): sponsors, grants, gate takings. Finance managers keep the
 * list of sources and record income by choosing one; the totals split what came in into internal (members)
 * and external, and external by source. */
export function ExternalIncomePage() {
  const { active } = useActiveMembership()
  const queryClient = useQueryClient()
  const orgId = active?.organization.id ?? ""
  const reader = can(active, "finances.view", "finances.manage")
  const manager = can(active, "finances.manage")
  const [from, setFrom] = useState(() => `${new Date().getFullYear()}-01-01`)
  const [to, setTo] = useState(today)
  const [source, setSource] = useState("")
  const sources = useQuery({ queryKey: externalKeys.sources(orgId), queryFn: () => listExternalSources(orgId), enabled: reader })
  const totals = useQuery({ queryKey: externalKeys.totals(orgId, from, to), queryFn: () => getIncomeTotals(orgId, from, to), enabled: reader })
  const income = useQuery({ queryKey: externalKeys.income(orgId, source, from, to), queryFn: () => listExternalIncome(orgId, source, from, to), enabled: reader })
  const refresh = () => queryClient.invalidateQueries({ queryKey: externalKeys.all(orgId) })

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club/finance">Finances</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Outside income</h1>
        <p className="text-muted-foreground">Money from outside the membership: sponsors, grants, gate takings. Members' dues and fees are internal.</p>
      </div>
      {!reader && <FormAlert>Outside income is for the club's finance staff.</FormAlert>}
      {reader && (
        <>
          <section aria-labelledby="totals-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
            <h2 id="totals-heading" className="text-xl font-bold">
              Received
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              <Field label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
            {totals.isError && <FormAlert>{errorMessage(totals.error)}</FormAlert>}
            {totals.data?.map((block) => (
              <dl key={block.currency} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
                <dt>Internal: from members</dt>
                <dd className="text-right tabular-nums">{formatMoney(block.internal_minor, block.currency)}</dd>
                <dt>External: from outside</dt>
                <dd className="text-right tabular-nums">{formatMoney(block.external_minor, block.currency)}</dd>
                {block.by_source.map((row) => (
                  <div key={row.source_id} className="col-span-2 grid grid-cols-[1fr_auto] gap-x-4 pl-4 text-sm text-muted-foreground">
                    <dt>{row.source_name}</dt>
                    <dd className="text-right tabular-nums">{formatMoney(row.amount_minor, block.currency)}</dd>
                  </div>
                ))}
                <dt className="border-t pt-1 font-semibold">Total</dt>
                <dd className="border-t pt-1 text-right font-semibold tabular-nums">{formatMoney(block.total_minor, block.currency)}</dd>
              </dl>
            ))}
          </section>

          {manager && sources.data && <Record orgId={orgId} sources={sources.data.filter((s) => s.active)} onDone={refresh} />}

          <section aria-labelledby="income-heading" className="flex flex-col gap-3">
            <h2 id="income-heading" className="text-xl font-bold">
              Income recorded
            </h2>
            <div className="max-w-xs">
              <SelectField label="Source" options={[{ value: "", label: "Every source" }, ...(sources.data ?? []).map((s) => ({ value: s.id, label: s.name }))]} value={source} onChange={setSource} />
            </div>
            {income.isError && <FormAlert>{errorMessage(income.error)}</FormAlert>}
            {income.isSuccess && income.data.length === 0 && <p className="text-muted-foreground">Nothing recorded in these dates.</p>}
            <ul className="flex flex-col gap-2">
              {income.data?.map((row) => (
                <IncomeRow key={row.id} orgId={orgId} row={row} manager={manager} onDone={refresh} />
              ))}
            </ul>
          </section>

          {sources.data && <Sources orgId={orgId} sources={sources.data} manager={manager} onDone={refresh} />}
        </>
      )}
    </div>
  )
}

function Record({ orgId, sources, onDone }: { orgId: string; sources: ExternalSource[]; onDone: () => void }) {
  const [source, setSource] = useState("")
  const [amount, setAmount] = useState("")
  const [on, setOn] = useState(today)
  const [description, setDescription] = useState("")
  const [reference, setReference] = useState("")
  // One key per form fill: pressing Save twice records the money once.
  const [key, setKey] = useState(() => crypto.randomUUID())
  const save = useMutation({
    mutationFn: () => recordExternalIncome(orgId, { source_id: source, amount_minor: toMinor(amount) ?? 0, currency: "KES", received_on: on, description: description.trim(), reference: reference.trim(), request_key: key }),
    onSuccess: () => {
      setAmount("")
      setDescription("")
      setReference("")
      setKey(crypto.randomUUID())
      onDone()
    },
  })
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <h2 className="text-xl font-bold">Record outside income</h2>
      {sources.length === 0 ? (
        <p className="text-muted-foreground">Add a source below first, such as Sponsor or County grant.</p>
      ) : (
        <>
          <SelectField label="Source" options={[{ value: "", label: "Choose a source" }, ...sources.map((s) => ({ value: s.id, label: s.name }))]} value={source} onChange={setSource} error={fields.source_id} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Amount (KES)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} error={fields.amount_minor} />
            <Field label="Received on" type="date" max={today()} value={on} onChange={(e) => setOn(e.target.value)} error={fields.received_on} />
          </div>
          <Field label="What for" optional maxLength={200} value={description} onChange={(e) => setDescription(e.target.value)} />
          <Field label="Reference" optional maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} hint="A receipt, cheque or M-Pesa reference, to match it later." />
          {save.isError && !Object.keys(fields).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
          <Button type="submit" className="self-start" disabled={!source || toMinor(amount) == null || !on || save.isPending}>
            {save.isPending ? "Saving…" : "Record income"}
          </Button>
        </>
      )}
    </form>
  )
}

function IncomeRow({ orgId, row, manager, onDone }: { orgId: string; row: ExternalIncome; manager: boolean; onDone: () => void }) {
  const [reason, setReason] = useState<string | null>(null)
  const reverse = useMutation({
    mutationFn: () => reverseExternalIncome(orgId, row.id, (reason ?? "").trim()),
    onSuccess: () => {
      setReason(null)
      onDone()
    },
  })
  return (
    <li className="flex flex-col gap-2 rounded-lg border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0">
          <span className={cn("font-semibold", row.reversed && "text-muted-foreground line-through")}>
            {row.source_name} · {formatMoney(row.amount_minor, row.currency)}
          </span>
          <span className="block text-sm text-muted-foreground">
            {formatDay(row.received_on)}
            {row.description && ` · ${row.description}`}
            {row.reference && ` · ${row.reference}`}
            {row.reversed && ` · reversed: ${row.reversal_reason}`}
          </span>
        </span>
        {manager && !row.reversed && reason === null && (
          <Button size="sm" variant="outline" onClick={() => setReason("")}>
            Reverse
          </Button>
        )}
      </div>
      {reason !== null && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Why it is reversed" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="The record stays, marked reversed." />
          <Button size="sm" variant="destructive" disabled={!reason.trim() || reverse.isPending} onClick={() => reverse.mutate()}>
            Reverse it
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setReason(null)}>
            Keep it
          </Button>
        </div>
      )}
      {reverse.isError && <FormAlert>{errorMessage(reverse.error)}</FormAlert>}
    </li>
  )
}

function Sources({ orgId, sources, manager, onDone }: { orgId: string; sources: ExternalSource[]; manager: boolean; onDone: () => void }) {
  const [name, setName] = useState("")
  const add = useMutation({
    mutationFn: () => addExternalSource(orgId, name.trim()),
    onSuccess: () => {
      setName("")
      onDone()
    },
  })
  const toggle = useMutation({ mutationFn: (s: ExternalSource) => setExternalSourceActive(orgId, s.id, !s.active), onSuccess: onDone })
  const remove = useMutation({ mutationFn: (s: ExternalSource) => deleteExternalSource(orgId, s.id), onSuccess: onDone })
  const fields: Record<string, string | undefined> = add.error instanceof ApiError ? add.error.fieldErrors() : {}
  const failed = toggle.error ?? remove.error
  return (
    <section aria-labelledby="sources-heading" className="flex flex-col gap-3 border-t pt-6">
      <h2 id="sources-heading" className="text-xl font-bold">
        Sources
      </h2>
      <p className="text-sm text-muted-foreground">Income is recorded under one of these, so reports stay consistent. A source that has been used is switched off, not deleted.</p>
      {failed && <FormAlert>{errorMessage(failed)}</FormAlert>}
      {sources.length === 0 && <p className="text-muted-foreground">No sources yet.</p>}
      <ul className="flex flex-col gap-2">
        {sources.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card px-3 py-2">
            <span className={cn("font-semibold", !s.active && "text-muted-foreground")}>
              {s.name}
              {!s.active && <span className="font-normal"> · switched off</span>}
            </span>
            {manager && (
              <span className="flex gap-1">
                <Button size="sm" variant="outline" disabled={toggle.isPending} onClick={() => toggle.mutate(s)}>
                  {s.active ? "Switch off" : "Switch on"}
                </Button>
                {!s.used && (
                  <Button size="sm" variant="outline" disabled={remove.isPending} aria-label={`Delete ${s.name}`} onClick={() => remove.mutate(s)}>
                    Delete
                  </Button>
                )}
              </span>
            )}
          </li>
        ))}
      </ul>
      {manager && (
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            add.mutate()
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <Field label="New source" className="min-w-48 flex-1" maxLength={80} placeholder="Sponsor" value={name} onChange={(e) => setName(e.target.value)} error={fields.name} />
          <Button type="submit" variant="outline" disabled={!name.trim() || add.isPending}>
            <Plus aria-hidden className="size-4" /> Add source
          </Button>
        </form>
      )}
    </section>
  )
}
