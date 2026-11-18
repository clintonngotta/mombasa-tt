import { useParams, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { Form } from "@/components/ratings/Form"
import { Processing } from "@/components/ratings/Processing"
import { RatingHistory } from "@/components/ratings/RatingHistory"
import { ApiError, errorMessage } from "@/lib/api"
import { DISCIPLINE_LABEL, getPlayerRatings, ratingKeys, shown, winRate, type Discipline, type RatingSummary, type ResultFilter } from "@/lib/ratings"
import { cn } from "@/lib/utils"

const RESULTS: { value: ResultFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
]

/** One player's singles and doubles ratings and the matches behind them, with filters that say what is shown (REQ-016). */
export function PlayerRatingsPage() {
  const { id = "" } = useParams()
  const [params, setParams] = useSearchParams()
  const discipline: Discipline = params.get("discipline") === "doubles" ? "doubles" : "singles"
  const result: ResultFilter = params.get("result") === "won" ? "won" : params.get("result") === "lost" ? "lost" : "all"
  const ratings = useQuery({
    queryKey: ratingKeys.player(id, discipline, result),
    queryFn: () => getPlayerRatings(id, discipline, result),
    refetchInterval: (query) => (query.state.data?.processing ? 5000 : false),
  })
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    next.set(key, value)
    setParams(next, { replace: true })
  }
  const data = ratings.data
  const gone = ratings.error instanceof ApiError && ratings.error.status === 404

  return (
    <div className="flex max-w-[720px] flex-col gap-5">
      <BackLink to="/rankings">Rankings</BackLink>
      {ratings.isPending && <p className="text-muted-foreground">Loading ratings…</p>}
      {ratings.isError && <FormAlert>{gone ? "This player has no ratings to show." : errorMessage(ratings.error, "We couldn't load these ratings.")}</FormAlert>}
      {data && (
        <>
          <header className="flex flex-col gap-1">
            <h1 className="text-[28px] leading-8 font-bold break-words">{data.display_name}</h1>
            <p className="text-muted-foreground">Ratings on the whole platform, from played tournament matches.</p>
          </header>
          {data.processing && <Processing />}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {data.summaries.map((summary) => (
              <Summary key={summary.discipline} summary={summary} selected={summary.discipline === discipline} />
            ))}
          </div>
          <section aria-labelledby="history-heading" className="flex flex-col gap-3">
            <h2 id="history-heading" className="text-2xl font-bold">
              {DISCIPLINE_LABEL[discipline]} rating history
            </h2>
            <div className="flex flex-wrap gap-3">
              <Segmented
                label="Discipline"
                value={discipline}
                onChange={(value) => set("discipline", value)}
                options={[
                  { value: "singles", label: DISCIPLINE_LABEL.singles },
                  { value: "doubles", label: DISCIPLINE_LABEL.doubles },
                ]}
              />
              <Segmented label="Results shown" value={result} onChange={(value) => set("result", value)} options={RESULTS} />
            </div>
            <RatingHistory userId={id} discipline={discipline} result={result} />
          </section>
        </>
      )}
    </div>
  )
}

function Summary({ summary, selected }: { summary: RatingSummary; selected: boolean }) {
  return (
    <div className={cn("flex flex-col gap-1 rounded-xl border bg-card p-4", selected && "border-brand-blue")}>
      <p className="text-sm font-semibold text-muted-foreground">{DISCIPLINE_LABEL[summary.discipline]} · whole platform</p>
      {summary.rating === null ? (
        <p className="text-muted-foreground">No rating yet. It starts at 1000 with the first played tournament match.</p>
      ) : (
        <>
          <p className="text-[32px] leading-9 font-bold tabular-nums">{shown(summary.rating)}</p>
          <p>
            Rank {summary.rank} of {summary.ranked}
          </p>
          <p className="text-sm text-muted-foreground">
            {summary.won} won of {summary.played} rated ({winRate(summary.won, summary.played)})
          </p>
          <Form form={summary.form} />
        </>
      )}
    </div>
  )
}
