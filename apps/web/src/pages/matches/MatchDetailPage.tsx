import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Lock, MapPin, Pencil, Trash2 } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { LabelPill, MatchSides, ResultBadge } from "@/components/matches/MatchSides"
import { errorMessage } from "@/lib/api"
import { deleteMatch, formatPlayedOn, getMatch, matchKeys } from "@/lib/matchlog"
import { cn } from "@/lib/utils"

export function MatchDetailPage() {
  const { id = "" } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const match = useQuery({ queryKey: matchKeys.detail(id), queryFn: () => getMatch(id) })

  const remove = useMutation({
    mutationFn: () => deleteMatch(id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: matchKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: matchKeys.all })
      navigate("/matches", { replace: true })
    },
  })

  const back = (
    <Link to="/matches" className="-ml-1 flex w-fit items-center gap-1 py-2 font-semibold text-brand-blue">
      <ArrowLeft aria-hidden className="size-5" /> My match log
    </Link>
  )

  if (match.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (match.isError) {
    return (
      <div className="flex max-w-[640px] flex-col gap-4">
        {back}
        <FormAlert>{errorMessage(match.error, "That match isn't in your log.")}</FormAlert>
      </div>
    )
  }

  const m = match.data
  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      {back}

      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <LabelPill label={m.label} />
          <ResultBadge result={m.result} />
          <span className="capitalize text-muted-foreground">{m.format}</span>
        </div>
        <h1 className="text-[32px] leading-9 font-bold">{formatPlayedOn(m.played_on)}</h1>
        {m.venue && (
          <p className="flex items-center gap-1.5 text-muted-foreground">
            <MapPin aria-hidden className="size-4" /> {m.venue}
          </p>
        )}
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Lock aria-hidden className="size-4" /> Self-recorded · private to you
        </p>
      </header>

      <section aria-label="Score" className="flex flex-col gap-5 rounded-2xl bg-brand-navy p-5 text-white [&_.text-muted-foreground]:text-white/50">
        <MatchSides match={m} size="lg" />
        <table className="w-full tabular">
          <caption className="sr-only">Points per set</caption>
          <thead className="sr-only">
            <tr>
              <th scope="col">Set</th>
              <th scope="col">Your points</th>
              <th scope="col">Opponent's points</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {m.games.map((g, i) => {
              const mineWon = g.my_points > g.opponent_points
              return (
                <tr key={i} className="grid grid-cols-[1fr_auto_1fr] items-center py-2">
                  <td className={cn("font-display text-2xl font-bold", mineWon ? "text-brand-gold" : "text-white/60")}>
                    {g.my_points}
                  </td>
                  <th scope="row" className="text-sm font-normal text-white/60">
                    Set {i + 1}
                  </th>
                  <td className={cn("text-right font-display text-2xl font-bold", !mineWon ? "text-brand-gold" : "text-white/60")}>
                    {g.opponent_points}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-xl">Notes</h2>
        {m.notes ? (
          <p className="whitespace-pre-wrap rounded-xl border bg-card p-4">{m.notes}</p>
        ) : (
          <p className="text-muted-foreground">No notes yet. Edit the match to add some.</p>
        )}
      </section>

      {remove.isError && <FormAlert>{errorMessage(remove.error, "We couldn't delete this match.")}</FormAlert>}
      <div className="flex flex-col gap-3 sm:flex-row">
        <Link to={`/matches/${m.id}/edit`} className={cn(buttonVariants({ variant: "outline" }), "sm:flex-1")}>
          <Pencil aria-hidden className="size-5" /> Edit
        </Link>
        {confirming ? (
          <div className="flex gap-2 sm:flex-1">
            <Button variant="destructive" className="flex-1" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {remove.isPending ? "Deleting…" : "Delete for good"}
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Keep
            </Button>
          </div>
        ) : (
          <Button variant="destructive" className="sm:flex-1" onClick={() => setConfirming(true)}>
            <Trash2 aria-hidden className="size-5" /> Delete
          </Button>
        )}
      </div>
    </div>
  )
}
