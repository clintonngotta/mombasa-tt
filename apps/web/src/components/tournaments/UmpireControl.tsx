import { useId, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { SearchSelect } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { drawKeys, type MatchDetail } from "@/lib/draws"
import { assignUmpire, listUmpires, SCORING_STATUS_LABEL, scoringKeys, type ScoringSummary } from "@/lib/scoring"
import { reservationKeys } from "@/lib/reservations"

type Ids = { tournamentId: string; eventId: string; matchId: string }

/**
 * Who scores a match or one rubber of a tie (REQ-012). Everybody sees the umpire's name and where the
 * scoring stands; only that umpire is offered the scoring deck, and only competition staff the choice
 * of umpire.
 */
export function UmpireControl({ scoring, ids, rubberId, what }: { scoring: ScoringSummary; ids: Ids; rubberId?: string; what: string }) {
  const queryClient = useQueryClient()
  const selectId = useId()
  const [choosing, setChoosing] = useState(false)
  const [chosen, setChosen] = useState("")
  const umpires = useQuery({ queryKey: scoringKeys.umpires(ids.eventId), queryFn: () => listUmpires(ids.tournamentId, ids.eventId), enabled: choosing })
  const assign = useMutation({
    mutationFn: (userId: string | null) => assignUmpire(ids.tournamentId, ids.eventId, ids.matchId, userId, rubberId),
    onSuccess: (fresh: MatchDetail) => {
      queryClient.setQueryData(drawKeys.match(ids.matchId), fresh)
      void queryClient.invalidateQueries({ queryKey: scoringKeys.mine })
      // The control centre shows the umpire on each table: read it again.
      void queryClient.invalidateQueries({ queryKey: reservationKeys.board(ids.tournamentId) })
      setChoosing(false)
    },
  })

  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold">{SCORING_STATUS_LABEL[scoring.status]}</span>
        {scoring.umpire_name && <span className="text-muted-foreground">Umpire: {scoring.umpire_name}</span>}
      </p>
      {scoring.can_score && scoring.scorecard_id && (
        <Link to={`/score/${scoring.scorecard_id}`} className={buttonVariants({ className: "self-start" })}>
          {scoring.status === "assigned" ? `Score ${what}` : `Carry on scoring ${what}`}
        </Link>
      )}
      {scoring.can_assign && !choosing && (
        <Button variant="outline" className="self-start" onClick={() => setChoosing(true)}>
          {scoring.umpire_name ? "Change the umpire" : "Assign an umpire"}
        </Button>
      )}
      {scoring.can_assign && choosing && (
        <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
          <label htmlFor={selectId} className="font-semibold">
            Umpire for {what}
          </label>
          {umpires.isError && <FormAlert>{errorMessage(umpires.error, "We couldn't load who can umpire.")}</FormAlert>}
          <SearchSelect
            id={selectId}
            value={chosen}
            onChange={setChosen}
            disabled={umpires.isPending}
            options={[
              { value: "", label: umpires.isPending ? "Loading…" : "Choose a member" },
              ...(umpires.data ?? []).map((umpire) => ({ value: umpire.id, label: umpire.display_name })),
            ]}
          />
          <p className="text-muted-foreground">The tournament's umpires, members whose role lets them score, and those who run competitions. A player can't umpire their own match.</p>
          {assign.isError && <FormAlert>{errorMessage(assign.error)}</FormAlert>}
          <div className="flex flex-wrap gap-2">
            <Button disabled={!chosen || assign.isPending} onClick={() => assign.mutate(chosen)}>
              {assign.isPending ? "Saving…" : "Assign"}
            </Button>
            {scoring.umpire_name && (
              <Button variant="outline" disabled={assign.isPending} onClick={() => assign.mutate(null)}>
                Take it back from {scoring.umpire_name}
              </Button>
            )}
            <Button variant="ghost" onClick={() => setChoosing(false)}>
              Close
            </Button>
          </div>
          <p className="text-muted-foreground">Assigning again cuts off the device that was scoring. The points already scored stay.</p>
        </div>
      )}
    </div>
  )
}
