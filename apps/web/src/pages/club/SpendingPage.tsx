import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { PurposeTotals } from "@/components/finance/PurposeTotals"
import { apiOriginUrl, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { useAdminAccessLost } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { campaignKeys, financeKeys, getFinanceSummary, listCampaigns, listExpenses, recordExpense, reverseExpense, toMinor, uploadReceipt, type Expense } from "@/lib/finance"

const SELECT = "h-12 rounded-md border bg-background px-3"
const today = () => new Date().toISOString().slice(0, 10)

/** Spending and what's left per purpose (REQ-024). Receipts are private to finance staff. */
export function SpendingPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "finances.view", "finances.manage")
  const manage = can(active, "finances.manage")
  const summary = useQuery({ queryKey: [...financeKeys.ledger(orgId), "summary"], queryFn: () => getFinanceSummary(orgId), enabled: allowed })
  const expenses = useQuery({ queryKey: [...financeKeys.ledger(orgId), "expenses"], queryFn: () => listExpenses(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(summary.error)
  const error = summary.error ?? expenses.error
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club/finance">Finances</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Spending</h1>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          {error && <FormAlert>{errorMessage(error)}</FormAlert>}
          <section className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold">By purpose</h2>
            <p className="text-sm text-muted-foreground">Received counts only payments matched to a purpose&apos;s dues and charges.</p>
            {summary.isSuccess && summary.data.length === 0 && <p className="text-muted-foreground">Nothing received or spent yet.</p>}
            <PurposeTotals rows={summary.data ?? []} />
          </section>
          {manage && <NewExpense orgId={orgId} />}
          <section className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold">Expenses</h2>
            {expenses.isSuccess && expenses.data.length === 0 && <p className="text-muted-foreground">No expenses recorded.</p>}
            <ul className="flex flex-col gap-2">
              {(expenses.data ?? []).map((e) => (
                <li key={e.id}>
                  <ExpenseRow orgId={orgId} expense={e} manage={manage} />
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}

function useSpendingMutation<T>(orgId: string, fn: (input: T) => Promise<unknown>, done?: () => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      done?.()
      return queryClient.invalidateQueries({ queryKey: financeKeys.ledger(orgId) })
    },
  })
}

function NewExpense({ orgId }: { orgId: string }) {
  const campaigns = useQuery({ queryKey: campaignKeys(orgId), queryFn: () => listCampaigns(orgId) })
  const [campaign, setCampaign] = useState("")
  const [description, setDescription] = useState("")
  const [amount, setAmount] = useState("")
  const [spent, setSpent] = useState(today)
  const add = useSpendingMutation(
    orgId,
    () => recordExpense(orgId, { campaign_id: campaign || null, description: description.trim(), amount_minor: toMinor(amount) ?? 0, currency: "KES", spent_on: spent }),
    () => {
      setDescription("")
      setAmount("")
    },
  )
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-semibold">Record spending</h2>
      <label className="flex flex-col gap-1 text-sm font-semibold">
        Paid from
        <select className={SELECT} value={campaign} onChange={(e) => setCampaign(e.target.value)}>
          <option value="">General running costs</option>
          {(campaigns.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="What for" className="min-w-48 flex-1" maxLength={200} value={description} onChange={(e) => setDescription(e.target.value)} />
        <Field label="Amount (KES)" type="number" min={0} className="w-36" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <Field label="Spent on" type="date" className="w-44" value={spent} onChange={(e) => setSpent(e.target.value)} />
      </div>
      <p className="text-sm text-muted-foreground">Members see what was spent and on what, never the receipts.</p>
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <Button className="self-start" disabled={!description.trim() || toMinor(amount) == null || !spent || add.isPending} onClick={() => add.mutate(undefined)}>
        Record expense
      </Button>
    </section>
  )
}

function ExpenseRow({ orgId, expense: e, manage }: { orgId: string; expense: Expense; manage: boolean }) {
  const [reason, setReason] = useState("")
  const reverse = useSpendingMutation(orgId, () => reverseExpense(orgId, e.id, reason.trim()))
  const receipt = useSpendingMutation(orgId, (file: File) => uploadReceipt(orgId, e.id, file))
  const error = reverse.error ?? receipt.error
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {e.description} · {formatMoney(e.amount_minor, e.currency)}
      </p>
      <p className="text-sm text-muted-foreground">
        {e.campaign_title ?? "General running costs"} · {e.spent_on}
        {e.reversed && ` · reversed: ${e.reversal_reason}`}
      </p>
      {e.receipt && (
        <a href={apiOriginUrl(e.receipt.url)} target="_blank" rel="noreferrer" className="self-start text-sm font-semibold text-brand-blue underline">
          See receipt
        </a>
      )}
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}
      {manage && !e.reversed && (
        <>
          <label className="flex flex-col gap-1 text-sm font-semibold">
            {e.receipt ? "Replace the receipt photo" : "Add a receipt photo"}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={receipt.isPending}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) receipt.mutate(file)
                event.target.value = ""
              }}
            />
          </label>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Reason to reverse" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(ev) => setReason(ev.target.value)} />
            <Button variant="outline" className="text-destructive" disabled={!reason.trim() || reverse.isPending} onClick={() => reverse.mutate(undefined)}>
              Reverse
            </Button>
          </div>
        </>
      )}
    </article>
  )
}
