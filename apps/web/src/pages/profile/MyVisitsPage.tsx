import { useQuery } from "@tanstack/react-query"
import { BadgeCheck, Lock } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { formatDay } from "@/lib/dates"
import { doorKeys, listMyVisits, METHOD_LABEL, type MyVisit } from "@/lib/door"
import { cn } from "@/lib/utils"

const todayHere = () => new Date().toLocaleDateString("en-CA")

/** The player's own passes and visits at facilities (REQ-044). An active pass is shown at the door. */
export function MyVisitsPage() {
  const visits = useQuery({ queryKey: doorKeys.mine, queryFn: listMyVisits })
  const all = visits.data?.results ?? []
  const today = todayHere()
  const passes = all.filter((v) => !v.reversed && !v.on_pass && v.valid_until >= today && v.pass_kind !== "day")

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/profile">Profile</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Passes and visits</h1>
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Lock aria-hidden className="size-4" /> Only you and the facility see these. Coast TT records what the facility collected; it never charges you.
      </p>
      {visits.isError && <FormAlert>{errorMessage(visits.error, "We couldn't load your visits.")}</FormAlert>}
      {passes.length > 0 && (
        <section aria-labelledby="passes-heading" className="flex flex-col gap-2">
          <h2 id="passes-heading" className="text-xl font-bold">
            Active passes
          </h2>
          {passes.map((pass) => (
            <div key={pass.id} className="flex flex-col gap-1 rounded-2xl bg-brand-navy p-5 text-white">
              <p className="flex items-center gap-2 text-lg font-bold">
                <BadgeCheck aria-hidden className="size-6 text-brand-gold" /> {pass.pass_name}
              </p>
              <p>
                {pass.venue_name} · {pass.facility_name}
              </p>
              <p className="text-white/80">Valid until {formatDay(pass.valid_until)}{pass.sessions ? ` · ${pass.sessions} visits` : ""}</p>
              {pass.benefits.length > 0 && <p className="text-sm text-white/80">{pass.benefits.join(" · ")}</p>}
            </div>
          ))}
        </section>
      )}
      <section aria-labelledby="visits-heading" className="flex flex-col gap-2">
        <h2 id="visits-heading" className="text-xl font-bold">
          Visits
        </h2>
        {visits.isSuccess && all.length === 0 && <p className="text-muted-foreground">No visits recorded yet.</p>}
        <ul className="flex flex-col gap-2">
          {all.map((visit) => (
            <li key={visit.id}>
              <VisitRow visit={visit} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function VisitRow({ visit }: { visit: MyVisit }) {
  return (
    <div className={cn(ROW, visit.reversed && "opacity-70")}>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={cn("font-semibold", visit.reversed && "line-through")}>
          {visit.venue_name} · {formatDay(visit.visited_on)}
        </span>
        <span className="text-sm text-muted-foreground">
          {visit.pass_name} · {visit.on_pass ? METHOD_LABEL.pass : `${formatMoney(visit.amount_minor, visit.currency)} ${METHOD_LABEL[visit.method]}`}
          {visit.reversed && " · reversed by the facility"}
        </span>
      </span>
    </div>
  )
}
