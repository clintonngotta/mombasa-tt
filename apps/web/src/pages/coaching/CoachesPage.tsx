import { useDeferredValue, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, GraduationCap } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Field, FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { coachingKeys, formatMoney, listCoaches } from "@/lib/coaching"
import { LEVEL_LABEL, SKILL_LABEL, type Skill } from "@/lib/training"
import { cn } from "@/lib/utils"

/** Find a coach (REQ-047): coaches taking players, by name, headline or town. */
export function CoachesPage() {
  const [search, setSearch] = useState("")
  const term = useDeferredValue(search.trim())
  const coaches = useQuery({ queryKey: coachingKeys.coaches(term), queryFn: () => listCoaches(term) })

  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <BackLink to="/training?tab=coaching">Coaching</BackLink>
      <div className="flex flex-col gap-2">
        <h1 className="text-[32px] leading-9 font-bold">Find a coach</h1>
        <p className="text-muted-foreground">Ask a coach to coach you, or book a session in their free hours.</p>
      </div>
      <Field label="Search" type="search" placeholder="Name, speciality or town" value={search} onChange={(e) => setSearch(e.target.value)} />
      {coaches.isError && <FormAlert>{errorMessage(coaches.error, "We couldn't load coaches.")}</FormAlert>}
      {coaches.isSuccess && coaches.data.results.length === 0 && (
        <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">No coaches found{term && ` for “${term}”`}.</p>
      )}
      <ul className="flex flex-col gap-2">
        {coaches.data?.results.map((coach) => (
          <li key={coach.id}>
            <Link to={`/coaches/${coach.user.id}`} className={cn(ROW, "flex-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
              <GraduationCap aria-hidden className="size-6 shrink-0 text-brand-blue" />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="font-semibold">{coach.user.display_name}</span>
                <span className="text-sm">{coach.headline}</span>
                <span className="text-sm text-muted-foreground">
                  {[
                    coach.town,
                    (coach.levels ?? []).map((l) => LEVEL_LABEL[l]).join(", "),
                    (coach.specialties ?? []).slice(0, 3).map((s) => SKILL_LABEL[s as Skill]).join(", "),
                    formatMoney(coach.rate_minor, coach.currency ?? "KES") && `${formatMoney(coach.rate_minor, coach.currency ?? "KES")} an hour`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <ChevronRight aria-hidden className="size-5 shrink-0 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
