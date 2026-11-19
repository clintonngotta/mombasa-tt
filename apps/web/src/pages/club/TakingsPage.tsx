import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { useAdminAccessLost } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { formatDay } from "@/lib/dates"
import { doorKeys, getTakings, METHOD_LABEL, type Takings } from "@/lib/door"
import { listVenues, venueKeys } from "@/lib/venues"

type Row = Takings["total"][number] & { label: string }

/** A month's door takings (REQ-044) for those who see the finances: per day, branch, method and pass.
 * Reversed visits are left out and counted separately. */
export function TakingsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "finances.view", "finances.manage")
  const [month, setMonth] = useState("")
  const [venue, setVenue] = useState("")
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId), enabled: allowed })
  const takings = useQuery({ queryKey: doorKeys.takings(orgId, month, venue), queryFn: () => getTakings(orgId, month, venue), enabled: allowed })
  const accessLost = useAdminAccessLost(takings.error)
  const t = takings.data

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Door takings</h1>
        {active && <p className="text-muted-foreground">{active.organization.name}</p>}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Month" type="month" value={month || t?.month || ""} onChange={(e) => setMonth(e.target.value)} />
            <SelectField label="Branch" value={venue} onChange={setVenue} options={[{ value: "", label: "All branches" }, ...(venues.data ?? []).map((v) => ({ value: v.id, label: v.name }))]} />
          </div>
          {takings.isError && <FormAlert>{errorMessage(takings.error, "We couldn't load the takings.")}</FormAlert>}
          {t && (
            <>
              <section aria-label="Month total" className="flex flex-wrap gap-6 rounded-xl border bg-card p-4">
                {t.total.length === 0 && <p className="text-muted-foreground">Nothing recorded this month.</p>}
                {t.total.map((row) => (
                  <p key={row.currency} className="flex flex-col">
                    <span className="text-3xl font-bold tabular-nums">{formatMoney(row.amount_minor, row.currency)}</span>
                    <span className="text-muted-foreground">
                      {row.visits} {row.visits === 1 ? "visit" : "visits"}
                    </span>
                  </p>
                ))}
                {t.reversed > 0 && <p className="self-end text-sm text-muted-foreground">{t.reversed} reversed, not counted</p>}
              </section>
              <Breakdown title="By day" rows={t.by_day.map((r) => ({ ...r, label: formatDay(r.day) }))} />
              <Breakdown title="By branch" rows={t.by_branch.map((r) => ({ ...r, label: r.venue_name }))} />
              <Breakdown title="By method" rows={t.by_method.map((r) => ({ ...r, label: METHOD_LABEL[r.method] ?? r.method }))} />
              <Breakdown title="By pass" rows={t.by_pass.map((r) => ({ ...r, label: r.pass_name }))} />
            </>
          )}
        </>
      )}
    </div>
  )
}

function Breakdown({ title, rows }: { title: string; rows: Row[] }) {
  if (!rows.length) return null
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xl font-bold">{title}</h2>
      <table className="w-full text-left">
        <thead className="text-sm text-muted-foreground">
          <tr>
            <th scope="col" className="py-1 font-semibold">
              {title.replace("By ", "").replace(/^./, (c) => c.toUpperCase())}
            </th>
            <th scope="col" className="py-1 text-right font-semibold">
              Visits
            </th>
            <th scope="col" className="py-1 text-right font-semibold">
              Collected
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.label}-${row.currency}`} className="border-t">
              <td className="py-2">{row.label}</td>
              <td className="py-2 text-right tabular-nums">{row.visits}</td>
              <td className="py-2 text-right tabular-nums">{formatMoney(row.amount_minor, row.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
