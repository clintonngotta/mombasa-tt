import { useQuery } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { useActiveMembership } from "@/lib/clubs"
import { ROW } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { CADENCE_LABEL, financeKeys, getMyFinances, METHOD_LABEL, STATUS_LABEL, type Campaign } from "@/lib/finance"

/** What the member owes this organization and what they have paid (REQ-022). Only their own. */
export function MyFinancesPage() {
  const { active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const mine = useQuery({ queryKey: financeKeys.mine(orgId), queryFn: () => getMyFinances(orgId), enabled: !!orgId })
  const data = mine.data
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">My payments</h1>
      {mine.isError && <FormAlert>{errorMessage(mine.error)}</FormAlert>}
      {data && (
        <>
          {data.balances.length === 0 ? (
            <p className="text-muted-foreground">You owe nothing.</p>
          ) : (
            data.balances.map((b) => (
              <p key={b.currency} className="text-lg font-semibold">
                {b.owed_minor > 0 ? `You owe ${formatMoney(b.owed_minor, b.currency)}` : "You owe nothing"}
                {b.credit_minor > 0 && ` · ${formatMoney(b.credit_minor, b.currency)} credit`}
              </p>
            ))
          )}
          {data.dues.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-xl font-semibold">Dues</h2>
              <ul className="flex flex-col gap-2">
                {data.dues.map((d) => (
                  <li key={d.campaign_id} className={ROW}>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="font-semibold">{d.title}</span>
                      <span className="text-sm text-muted-foreground">
                        {CADENCE_LABEL[d.cadence as Campaign["cadence"]] ?? d.cadence}
                        {d.outstanding_minor > 0 ? ` · ${formatMoney(d.outstanding_minor, d.currency)} to pay` : " · all paid"}
                        {d.overdue_minor > 0 && ` · ${formatMoney(d.overdue_minor, d.currency)} overdue`}
                        {d.next_due_on && ` · next due ${d.next_due_on}`}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold">Charges</h2>
            {data.charges.length === 0 && <p className="text-muted-foreground">No charges.</p>}
            <ul className="flex flex-col gap-2">
              {data.charges.map((c) => (
                <li key={c.id} className={ROW}>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="font-semibold">{c.purpose}</span>
                    <span className="text-sm text-muted-foreground">
                      {formatMoney(c.amount_minor, c.currency)} · {STATUS_LABEL[c.status] ?? c.status}
                      {c.outstanding_minor > 0 && ` · ${formatMoney(c.outstanding_minor, c.currency)} left`}
                      {c.due_on && ` · due ${c.due_on}`}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <section className="flex flex-col gap-2">
            <h2 className="text-xl font-semibold">Payments</h2>
            {data.payments.length === 0 && <p className="text-muted-foreground">No payments recorded.</p>}
            <ul className="flex flex-col gap-2">
              {data.payments.map((p) => (
                <li key={p.id} className={ROW}>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="font-semibold">
                      {formatMoney(p.amount_minor, p.currency)} by {METHOD_LABEL[p.method]}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {p.received_on}
                      {p.reversed && ` · reversed: ${p.reversal_reason}`}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
