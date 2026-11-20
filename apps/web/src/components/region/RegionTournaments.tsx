import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { TournamentStatusChip } from "@/components/tournaments/StatusChip"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { can, setActiveOrganization, type Membership } from "@/lib/clubs"
import { formatDayRange } from "@/lib/dates"
import { listOverseenTournaments, organizerLine, SCOPE_LABEL, tournamentKeys, type When } from "@/lib/tournaments"
import { cn } from "@/lib/utils"

/** Published tournaments organized in the official's region, by clubs, facilities, coaches or the regional
 * body itself (REQ-048): what they oversee, upcoming or past. */
export function OverseenTournaments() {
  const [when, setWhen] = useState<When>("upcoming")
  const found = useQuery({ queryKey: [...tournamentKeys.all, "overseen", when], queryFn: () => listOverseenTournaments(when) })
  const rows = found.data?.results ?? []
  return (
    <section aria-labelledby="overseen-tournaments-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="overseen-tournaments-heading" className="text-xl font-bold">
          Tournaments in your region
        </h2>
        <div role="group" aria-label="When" className="flex gap-1">
          {(["upcoming", "past"] as const).map((value) => (
            <Button key={value} type="button" size="sm" variant={when === value ? "default" : "outline"} aria-pressed={when === value} onClick={() => setWhen(value)}>
              {value === "upcoming" ? "Upcoming" : "Past"}
            </Button>
          ))}
        </div>
      </div>
      <p className="text-sm text-muted-foreground">Every published tournament organized in your jurisdiction, whoever runs it.</p>
      {found.isPending && <p className="text-muted-foreground">Loading tournaments…</p>}
      {found.isError && <FormAlert>{errorMessage(found.error, "We couldn't load the region's tournaments.")}</FormAlert>}
      {found.isSuccess && rows.length === 0 && <p className="text-muted-foreground">{when === "upcoming" ? "No tournaments coming up." : "No past tournaments."}</p>}
      <ul className="flex flex-col gap-2">
        {rows.map((t) => (
          <li key={t.id}>
            <Link to={`/tournaments/${t.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold break-words">{t.name}</span>
                <span className="text-sm text-muted-foreground">
                  {formatDayRange(t.starts_on, t.ends_on)} · {SCOPE_LABEL[t.scope]}
                </span>
                <span className="text-sm text-muted-foreground">Organized by {organizerLine(t)}</span>
              </span>
              {t.status !== "published" && <TournamentStatusChip status={t.status} />}
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Regional officials organize tournaments through their regional body, which players see as the
 * organizer (e.g. "Coast Table Tennis Committee"). */
export function OrganizeAsBody({ body }: { body: Membership }) {
  const navigate = useNavigate()
  if (!can(body, "competitions.manage")) return null
  return (
    <div className={cn(ROW, "flex-wrap justify-between")}>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-semibold">Organize a tournament</span>
        <span className="text-sm text-muted-foreground">Players see {body.organization.name} as the organizer.</span>
      </span>
      <Button
        type="button"
        onClick={() => {
          setActiveOrganization(body.organization.id)
          navigate("/club/tournaments/new")
        }}
      >
        <Plus aria-hidden className="size-5" /> New tournament
      </Button>
    </div>
  )
}
