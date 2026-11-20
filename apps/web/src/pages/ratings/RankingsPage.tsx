import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ArrowDownRight, ArrowUpRight, ChevronDown } from "lucide-react"
import { FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { SelectField } from "@/components/forms/SelectField"
import { Form } from "@/components/ratings/Form"
import { Processing } from "@/components/ratings/Processing"
import { RatingHistory } from "@/components/ratings/RatingHistory"
import { buttonVariants } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { countryName } from "@/lib/geography"
import { DISCIPLINE_LABEL, getClubRanking, getGeographyRanking, getRanking, ratingKeys, shown, signed, winRate, type Discipline, type GeographyLevel, type RankingRow } from "@/lib/ratings"
import { cn } from "@/lib/utils"

type RankingTab = "players" | "clubs" | "geography"

const ratingPoints = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })
const GEOGRAPHY_LABEL: Record<GeographyLevel, string> = { country: "Countries", region: "Regions", city: "Cities" }

/**
 * Ratings by discipline, for individual players or by the points their clubs hold together.
 */
export function RankingsPage() {
  const [tab, setTab] = useState<RankingTab>("players")
  const [discipline, setDiscipline] = useState<Discipline>("singles")
  const [organizationId, setOrganizationId] = useState("")
  const { results: active } = useMemberships()
  const ranking = useQuery({
    queryKey: ratingKeys.ranking(discipline, organizationId),
    queryFn: () => getRanking(discipline, organizationId),
    enabled: tab === "players",
    // While a result is still being worked in, look again by itself.
    refetchInterval: (query) => (query.state.data?.processing ? 5000 : false),
  })
  const data = ranking.data
  const scope = data ? (data.scope === "club" ? data.organization_name : "Whole platform") : ""

  return (
    <div className="flex max-w-[820px] flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Rankings</h1>
        <p className="text-muted-foreground">Ratings change only with played tournament matches. Walkovers, retirements and casual games don't count.</p>
      </header>
      <Segmented
        label="Rankings"
        value={tab}
        onChange={setTab}
        options={[{ value: "players", label: "Players" }, { value: "clubs", label: "Clubs" }, { value: "geography", label: "Geography" }]}
      />
      <div className="flex flex-wrap items-end gap-3">
        <Segmented
          label="Discipline"
          value={discipline}
          onChange={setDiscipline}
          options={[
            { value: "singles", label: DISCIPLINE_LABEL.singles },
            { value: "doubles", label: DISCIPLINE_LABEL.doubles },
          ]}
        />
        {tab === "players" && active.length > 0 && (
          <div className="min-w-[220px] flex-1">
            <SelectField
              label="Among"
              value={organizationId}
              onChange={setOrganizationId}
              options={[
                { value: "", label: "Whole platform" },
                ...active.map(({ organization }) => ({ value: organization.id, label: `Members of ${organization.name}` })),
              ]}
            />
          </div>
        )}
      </div>
      {tab === "clubs" && <ClubRankings discipline={discipline} />}
      {tab === "geography" && <GeographyRankings discipline={discipline} />}
      {tab === "players" && ranking.isPending && <p className="text-muted-foreground">Loading the ranking…</p>}
      {tab === "players" && ranking.isError && <FormAlert>{errorMessage(ranking.error, "We couldn't load the ranking.")}</FormAlert>}
      {tab === "players" && data && (
        <section aria-labelledby="ranking-heading" className="flex flex-col gap-3">
          <h2 id="ranking-heading" className="text-2xl font-bold">
            {DISCIPLINE_LABEL[data.discipline]} · {scope}
          </h2>
          {data.processing && <Processing />}
          {data.rows.length === 0 ? (
            <p className="text-muted-foreground">Nobody has a {data.discipline} rating here yet. A rating starts at 1000 with the first played tournament match.</p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                {data.count} rated {data.count === 1 ? "player" : "players"}
                {data.count > data.rows.length && `, the top ${data.rows.length} shown`}. Open a row for the matches behind the rating.
              </p>
              <ol className="flex flex-col gap-2">
                {data.rows.map((row) => (
                  <Row key={row.user_id} row={row} discipline={data.discipline} />
                ))}
              </ol>
            </>
          )}
        </section>
      )}
    </div>
  )
}

function ClubRankings({ discipline }: { discipline: Discipline }) {
  const ranking = useQuery({
    queryKey: ratingKeys.clubs(discipline),
    queryFn: () => getClubRanking(discipline),
    refetchInterval: (query) => (query.state.data?.processing ? 5000 : false),
  })
  return (
    <section aria-labelledby="club-rankings-heading" className="flex flex-col gap-3">
      <h2 id="club-rankings-heading" className="text-2xl font-bold">{DISCIPLINE_LABEL[discipline]} · Clubs</h2>
      <p className="text-sm text-muted-foreground">Club points are the sum of current ratings for active members with a played match in this discipline.</p>
      {ranking.isPending && <p className="text-muted-foreground">Loading club rankings…</p>}
      {ranking.isError && <FormAlert>{errorMessage(ranking.error, "We couldn't load the club rankings.")}</FormAlert>}
      {ranking.data?.processing && <Processing />}
      {ranking.data?.rows.length === 0 && <p className="text-muted-foreground">No clubs have rated {discipline} members yet.</p>}
      <AggregateList rows={ranking.data?.rows.map((club) => ({
        id: club.organization_id,
        rank: club.rank,
        name: club.name,
        context: [club.town, `${club.rated_members} rated ${club.rated_members === 1 ? "member" : "members"}`].filter(Boolean).join(" · "),
        points: club.total_points,
      })) ?? []} />
    </section>
  )
}

function GeographyRankings({ discipline }: { discipline: Discipline }) {
  const [level, setLevel] = useState<GeographyLevel>("country")
  const ranking = useQuery({
    queryKey: ratingKeys.geography(discipline, level),
    queryFn: () => getGeographyRanking(discipline, level),
    refetchInterval: (query) => (query.state.data?.processing ? 5000 : false),
  })
  return (
    <section aria-labelledby="geography-rankings-heading" className="flex flex-col gap-3">
      <Segmented
        label="Geographic ranking"
        value={level}
        onChange={setLevel}
        options={[
          { value: "country", label: "Countries" },
          { value: "region", label: "Regions" },
          { value: "city", label: "Cities" },
        ]}
      />
      <h2 id="geography-rankings-heading" className="text-2xl font-bold">{DISCIPLINE_LABEL[discipline]} · {GEOGRAPHY_LABEL[level]}</h2>
      <p className="text-sm text-muted-foreground">Points are the combined current ratings of players who list that location.</p>
      {ranking.isPending && <p className="text-muted-foreground">Loading geographic rankings…</p>}
      {ranking.isError && <FormAlert>{errorMessage(ranking.error, "We couldn't load the geographic rankings.")}</FormAlert>}
      {ranking.data?.processing && <Processing />}
      {ranking.data?.rows.length === 0 && <p className="text-muted-foreground">No rated {discipline} players have added a location here yet.</p>}
      <AggregateList rows={ranking.data?.rows.map((row) => {
        const country = countryName(row.country)
        const context = level === "city" ? [row.region, country] : level === "region" ? [country] : []
        return {
          id: JSON.stringify([row.country, row.region, row.city]),
          rank: row.rank,
          name: row.city || row.region || country,
          context: [...context, `${row.rated_players} rated ${row.rated_players === 1 ? "player" : "players"}`].join(" · "),
          points: row.total_points,
        }
      }) ?? []} />
    </section>
  )
}

function AggregateList({ rows }: {
  rows: { id: string; rank: number; name: string; context: string; points: number }[]
}) {
  if (rows.length === 0) return null
  return (
    <ol className="flex flex-col gap-2">
      {rows.map((row) => (
        <li key={row.id} className="flex min-h-16 items-center gap-3 rounded-xl border bg-card p-3">
          <span aria-label={`Rank ${row.rank}`} className="w-8 shrink-0 text-center text-lg font-bold tabular-nums">{row.rank}</span>
          <span className="flex min-w-0 flex-1 flex-col break-words">
            <span className="font-semibold">{row.name}</span>
            <span className="text-sm text-muted-foreground">{row.context}</span>
          </span>
          <span className="flex shrink-0 flex-col items-end">
            <span className="text-xl font-bold tabular-nums">{ratingPoints.format(row.points)}</span>
            <span className="text-sm text-muted-foreground">points</span>
          </span>
        </li>
      ))}
    </ol>
  )
}

function Row({ row, discipline }: { row: RankingRow; discipline: Discipline }) {
  const [open, setOpen] = useState(false)
  return (
    <li className={cn("rounded-xl border bg-card", row.is_me && "border-brand-blue")}>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex min-h-12 w-full items-center gap-3 rounded-xl p-3 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
        <span className="w-8 shrink-0 text-center text-lg font-bold tabular-nums" aria-label={`Rank ${row.rank}`}>
          {row.rank}
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-semibold break-words">
            {row.display_name}
            {row.is_me && <span className="font-normal text-muted-foreground"> (you)</span>}
          </span>
          {row.clubs.length > 0 && <span className="text-sm break-words text-muted-foreground">{row.clubs.join(", ")}</span>}
          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
            <span>
              {row.won} won of {row.played} ({winRate(row.won, row.played)})
            </span>
            <Form form={row.form} />
          </span>
        </span>
        <span className="flex shrink-0 flex-col items-end">
          <span className="text-xl font-bold tabular-nums">{shown(row.rating)}</span>
          {row.last_delta !== null && (
            <span className={cn("flex items-center gap-0.5 text-sm font-semibold tabular-nums", row.last_delta < 0 ? "text-destructive" : "text-success")}>
              {row.last_delta < 0 ? <ArrowDownRight aria-hidden className="size-4" /> : <ArrowUpRight aria-hidden className="size-4" />}
              {signed(row.last_delta)} last
            </span>
          )}
        </span>
        <ChevronDown aria-hidden className={cn("size-5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t p-3">
          <RatingHistory userId={row.user_id} discipline={discipline} limit={5} />
          <div className="flex flex-wrap gap-2">
            <Link to={`/ratings/${row.user_id}?discipline=${discipline}`} className={buttonVariants({ variant: "outline" })}>
              Full rating history
            </Link>
            {row.listed && (
              <Link to={`/players/${row.user_id}`} className={buttonVariants({ variant: "ghost" })}>
                Player page
              </Link>
            )}
          </div>
        </div>
      )}
    </li>
  )
}
