import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { errorMessage } from "@/lib/api"
import { can, listMembers, useActiveMembership } from "@/lib/clubs"
import { useAdminAccessLost } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import {
  allocatePayment,
  createCharge,
  financeKeys,
  KIND_LABEL,
  listBalances,
  listCharges,
  listPayments,
  METHOD_LABEL,
  recordPayment,
  reversePayment,
  STATUS_LABEL,
  toMinor,
  waiveCharge,
  type Charge,
  type Payment,
} from "@/lib/finance"

const SELECT = "h-12 rounded-md border bg-background px-3"
const today = () => new Date().toISOString().slice(0, 10)

/** The organization's ledger (REQ-022): what members owe, what they paid and how payments are applied. */
export function ClubFinancePage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "finances.view", "finances.manage")
  const manage = can(active, "finances.manage")
  const charges = useQuery({ queryKey: [...financeKeys.ledger(orgId), "charges"], queryFn: () => listCharges(orgId), enabled: allowed })
  const payments = useQuery({ queryKey: [...financeKeys.ledger(orgId), "payments"], queryFn: () => listPayments(orgId), enabled: allowed })
  const balances = useQuery({ queryKey: [...financeKeys.ledger(orgId), "balances"], queryFn: () => listBalances(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(charges.error)
  const error = charges.error ?? payments.error ?? balances.error
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Finances</h1>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          {error && <FormAlert>{errorMessage(error)}</FormAlert>}
          <section className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold">Balances</h2>
            {balances.isSuccess && balances.data.length === 0 && <p className="text-muted-foreground">Nothing owed and no credit.</p>}
            <ul className="flex flex-col gap-1">
              {(balances.data ?? []).map((b) => (
                <li key={`${b.member_id}-${b.currency}`} className="flex justify-between rounded-lg border bg-card px-4 py-3">
                  <span className="font-semibold">{b.member_name}</span>
                  <span className="text-sm">
                    {b.owed_minor > 0 && `Owes ${formatMoney(b.owed_minor, b.currency)}`}
                    {b.owed_minor > 0 && b.credit_minor > 0 && " · "}
                    {b.credit_minor > 0 && `Credit ${formatMoney(b.credit_minor, b.currency)}`}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          {manage && <NewCharge orgId={orgId} />}
          <section className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold">Charges</h2>
            {charges.isSuccess && charges.data.length === 0 && <p className="text-muted-foreground">No charges.</p>}
            <ul className="flex flex-col gap-2">
              {(charges.data ?? []).map((c) => (
                <li key={c.id}>
                  <ChargeRow orgId={orgId} charge={c} manage={manage} />
                </li>
              ))}
            </ul>
          </section>
          {manage && <NewPayment orgId={orgId} />}
          <section className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold">Payments</h2>
            {payments.isSuccess && payments.data.length === 0 && <p className="text-muted-foreground">No payments recorded.</p>}
            <ul className="flex flex-col gap-2">
              {(payments.data ?? []).map((p) => (
                <li key={p.id}>
                  <PaymentRow orgId={orgId} payment={p} charges={charges.data ?? []} manage={manage} />
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}

function useLedgerMutation<T>(orgId: string, fn: (input: T) => Promise<unknown>, done?: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      done?.()
      return queryClient.invalidateQueries({ queryKey: financeKeys.ledger(orgId) })
    },
  })
}

function MemberSelect({ orgId, value, onChange, label }: { orgId: string; value: string; onChange: (id: string) => void; label: string }) {
  const members = useQuery({ queryKey: ["finance", "members", orgId], queryFn: () => listMembers(orgId, "") })
  return (
    <label className="flex flex-col gap-1 text-sm font-semibold">
      {label}
      <select className={SELECT} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a member</option>
        {(members.data?.results ?? []).map((m) => (
          <option key={m.id} value={m.user}>
            {m.display_name}
          </option>
        ))}
      </select>
    </label>
  )
}

function NewCharge({ orgId }: { orgId: string }) {
  const [member, setMember] = useState("")
  const [purpose, setPurpose] = useState("")
  const [amount, setAmount] = useState("")
  const [kind, setKind] = useState<Charge["kind"]>("other")
  const [due, setDue] = useState("")
  const add = useLedgerMutation(orgId, () => createCharge(orgId, { member_id: member, purpose: purpose.trim(), amount_minor: toMinor(amount) ?? 0, kind, currency: "KES", due_on: due || null }), () => {
    setPurpose("")
    setAmount("")
  })
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-semibold">Add a charge</h2>
      <MemberSelect orgId={orgId} value={member} onChange={setMember} label="Member" />
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-sm font-semibold">
          Kind
          <select className={SELECT} value={kind} onChange={(e) => setKind(e.target.value as Charge["kind"])}>
            {Object.entries(KIND_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Field label="For" className="min-w-48 flex-1" maxLength={120} value={purpose} onChange={(e) => setPurpose(e.target.value)} />
        <Field label="Amount (KES)" type="number" min={0} className="w-36" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <Field label="Due" optional type="date" className="w-44" value={due} onChange={(e) => setDue(e.target.value)} />
      </div>
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <Button className="self-start" disabled={!member || !purpose.trim() || toMinor(amount) == null || add.isPending} onClick={() => add.mutate(undefined)}>
        Add charge
      </Button>
    </section>
  )
}

function NewPayment({ orgId }: { orgId: string }) {
  const [payer, setPayer] = useState("")
  const [amount, setAmount] = useState("")
  const [method, setMethod] = useState<Payment["method"]>("mpesa")
  const [reference, setReference] = useState("")
  const [received, setReceived] = useState(today)
  // One key per payment being entered: pressing Record twice records it once.
  const [key, setKey] = useState(() => crypto.randomUUID())
  const record = useLedgerMutation(
    orgId,
    () => recordPayment(orgId, { payer_id: payer, amount_minor: toMinor(amount) ?? 0, currency: "KES", method, reference: reference.trim(), received_on: received, request_key: key }),
    () => {
      setAmount("")
      setReference("")
      setKey(crypto.randomUUID())
    },
  )
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-semibold">Record a payment</h2>
      <p className="text-sm text-muted-foreground">Payments are taken outside the app; this records them.</p>
      <MemberSelect orgId={orgId} value={payer} onChange={setPayer} label="Paid by" />
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Amount (KES)" type="number" min={0} className="w-36" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <label className="flex flex-col gap-1 text-sm font-semibold">
          Method
          <select className={SELECT} value={method} onChange={(e) => setMethod(e.target.value as Payment["method"])}>
            {Object.entries(METHOD_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Field label="Reference" optional className="w-40" maxLength={60} value={reference} onChange={(e) => setReference(e.target.value)} />
        <Field label="Received" type="date" className="w-44" value={received} onChange={(e) => setReceived(e.target.value)} />
      </div>
      {record.isError && <FormAlert>{errorMessage(record.error)}</FormAlert>}
      <Button className="self-start" disabled={!payer || toMinor(amount) == null || !received || record.isPending} onClick={() => record.mutate(undefined)}>
        Record payment
      </Button>
    </section>
  )
}

function ChargeRow({ orgId, charge: c, manage }: { orgId: string; charge: Charge; manage: boolean }) {
  const [reason, setReason] = useState("")
  const waive = useLedgerMutation(orgId, () => waiveCharge(orgId, c.id, reason.trim()))
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {c.member_name} · {c.purpose}
      </p>
      <p className="text-sm text-muted-foreground">
        {KIND_LABEL[c.kind]} · {formatMoney(c.amount_minor, c.currency)} · {STATUS_LABEL[c.status] ?? c.status}
        {c.outstanding_minor > 0 && ` · ${formatMoney(c.outstanding_minor, c.currency)} left`}
        {c.due_on && ` · due ${c.due_on}`}
        {c.waive_reason && ` · ${c.waive_reason}`}
      </p>
      {waive.isError && <FormAlert>{errorMessage(waive.error)}</FormAlert>}
      {manage && c.status !== "waived" && c.status !== "paid" && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Reason to waive" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button variant="outline" disabled={!reason.trim() || waive.isPending} onClick={() => waive.mutate(undefined)}>
            Waive
          </Button>
        </div>
      )}
    </article>
  )
}

function PaymentRow({ orgId, payment: p, charges, manage }: { orgId: string; payment: Payment; charges: Charge[]; manage: boolean }) {
  const open = charges.filter((c) => c.member_id === p.payer_id && c.currency === p.currency && c.outstanding_minor > 0)
  const [chargeId, setChargeId] = useState("")
  const [amount, setAmount] = useState("")
  const [reason, setReason] = useState("")
  const allocate = useLedgerMutation(orgId, () => allocatePayment(orgId, p.id, chargeId, toMinor(amount) ?? 0), () => setAmount(""))
  const reverse = useLedgerMutation(orgId, () => reversePayment(orgId, p.id, reason.trim()))
  const error = allocate.error ?? reverse.error
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {p.payer_name} · {formatMoney(p.amount_minor, p.currency)} by {METHOD_LABEL[p.method]}
        {p.reference && ` (${p.reference})`}
      </p>
      <p className="text-sm text-muted-foreground">
        Received {p.received_on}
        {p.reversed ? ` · reversed: ${p.reversal_reason}` : ` · ${formatMoney(p.allocated_minor, p.currency)} applied`}
        {p.credit_minor > 0 && ` · ${formatMoney(p.credit_minor, p.currency)} credit`}
      </p>
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}
      {manage && !p.reversed && p.credit_minor > 0 && open.length > 0 && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm font-semibold">
            Apply to
            <select className={SELECT} value={chargeId} onChange={(e) => setChargeId(e.target.value)}>
              <option value="">Choose a charge</option>
              {open.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.purpose} · {formatMoney(c.outstanding_minor, c.currency)} left
                </option>
              ))}
            </select>
          </label>
          <Field label="Amount (KES)" type="number" min={0} className="w-36" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Button disabled={!chargeId || toMinor(amount) == null || allocate.isPending} onClick={() => allocate.mutate(undefined)}>
            Apply
          </Button>
        </div>
      )}
      {manage && !p.reversed && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Reason to reverse" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button variant="outline" className="text-destructive" disabled={!reason.trim() || reverse.isPending} onClick={() => reverse.mutate(undefined)}>
            Reverse
          </Button>
        </div>
      )}
    </article>
  )
}
