import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CupSoda, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { PlayerPicker, type Picked } from "@/components/tournaments/PlayerPicker"
import { ApiError, errorMessage } from "@/lib/api"
import { fromZonedInput } from "@/lib/dates"
import {
  acceptChallenge,
  confirmResult,
  counterChallenge,
  createChallenge,
  declineChallenge,
  disputeResult,
  getSodaSettings,
  listChallenges,
  opponentOf,
  recordResult,
  settlePledge,
  shareChallenge,
  sodaKeys,
  stakeText,
  STATUS_LABEL,
  withdrawChallenge,
  type Challenge,
} from "@/lib/soda"
import { LOCAL_TIME_ZONE } from "@/lib/training"

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "Next time you meet"

/**
 * Soda games (REQ-040): friendly challenges between two players. Unrated, no table booked, and Coast TT
 * never handles money: a stake, where available, is only a record of what the loser pledged.
 */
export function SodaGamesPage() {
  const settings = useQuery({ queryKey: sodaKeys.settings, queryFn: getSodaSettings })
  const challenges = useQuery({ queryKey: sodaKeys.list, queryFn: listChallenges })
  const [creating, setCreating] = useState(false)
  const all = challenges.data?.results ?? []
  const waiting = all.filter((c) => c.mine === "challenged" && c.status === "pending")
  const rest = all.filter((c) => !waiting.includes(c))
  const stakes = settings.data?.stakes_available ?? false

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/play">Play</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="flex items-center gap-2 text-[32px] leading-9 font-bold">
          <CupSoda aria-hidden className="size-8 text-brand-blue" /> Soda games
        </h1>
        <p className="text-muted-foreground">Friendly challenges. They never change ratings or rankings and don't book a table.</p>
      </div>
      {settings.data && !settings.data.games_enabled && <FormAlert>Your club has switched soda games off.</FormAlert>}
      {settings.data?.games_enabled &&
        (creating ? (
          <NewChallenge stakes={stakes} onClose={() => setCreating(false)} />
        ) : (
          <Button className="self-start" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="size-5" /> Challenge a player
          </Button>
        ))}
      {challenges.isError && <FormAlert>{errorMessage(challenges.error, "We couldn't load your challenges.")}</FormAlert>}
      {waiting.length > 0 && (
        <section aria-labelledby="inbox-heading" className="flex flex-col gap-2">
          <h2 id="inbox-heading" className="text-xl font-bold">
            Challenges for you
          </h2>
          {waiting.map((c) => (
            <ChallengeCard key={c.id} challenge={c} />
          ))}
        </section>
      )}
      <section aria-labelledby="mine-heading" className="flex flex-col gap-2">
        <h2 id="mine-heading" className="text-xl font-bold">
          Your games
        </h2>
        {challenges.isSuccess && rest.length === 0 && <p className="text-muted-foreground">No soda games yet.</p>}
        {rest.map((c) => (
          <ChallengeCard key={c.id} challenge={c} />
        ))}
      </section>
    </div>
  )
}

function NewChallenge({ stakes, onClose }: { stakes: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const draft = useDraft("challenge-new")
  const [opponent, setOpponent] = useDraftState<Picked[]>(draft, "opponent", [])
  const [format, setFormat] = useDraftState<"singles" | "doubles">(draft, "format", "singles")
  const [bestOf, setBestOf] = useDraftState<"3" | "5">(draft, "bestOf", "3")
  const [playAt, setPlayAt] = useDraftState(draft, "playAt", "")
  const [place, setPlace] = useDraftState(draft, "place", "")
  const [message, setMessage] = useDraftState(draft, "message", "")
  const [myPartner, setMyPartner] = useDraftState(draft, "myPartner", "")
  const [theirPartner, setTheirPartner] = useDraftState(draft, "theirPartner", "")
  const [stakeKind, setStakeKind] = useDraftState<"none" | "money" | "thing">(draft, "stakeKind", "none")
  const [amount, setAmount] = useDraftState(draft, "amount", "")
  const [thing, setThing] = useDraftState(draft, "thing", "")
  const save = useMutation({
    mutationFn: () =>
      createChallenge({
        challenged_id: opponent[0]?.id ?? "",
        format,
        best_of: Number(bestOf),
        play_at: playAt ? fromZonedInput(playAt, LOCAL_TIME_ZONE) : null,
        place: place.trim(),
        message: message.trim(),
        challenger_partner: format === "doubles" ? myPartner.trim() : "",
        challenged_partner: format === "doubles" ? theirPartner.trim() : "",
        ...(stakes && stakeKind === "money" ? { stake_minor: Math.round(Number(amount) * 100), stake_currency: "KES" } : {}),
        ...(stakes && stakeKind === "thing" ? { stake_note: thing.trim() } : {}),
      }),
    onSuccess: () => {
      draft.clear()
      void queryClient.invalidateQueries({ queryKey: sodaKeys.all })
      onClose()
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">New challenge</h2>
      <PlayerPicker label="Who" hint="A club mate or a player in the directory." picked={opponent} max={1} onChange={setOpponent} error={errors.challenged_id} />
      <ChoiceGroup legend="Game" options={[{ value: "singles" as const, label: "Singles" }, { value: "doubles" as const, label: "Doubles" }]} value={format} onChange={setFormat} />
      {format === "doubles" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Your partner" optional maxLength={80} value={myPartner} onChange={(e) => setMyPartner(e.target.value)} />
          <Field label="Their partner" optional maxLength={80} value={theirPartner} onChange={(e) => setTheirPartner(e.target.value)} />
        </div>
      )}
      <ChoiceGroup legend="Best of" options={[{ value: "3" as const, label: "3 games" }, { value: "5" as const, label: "5 games" }]} value={bestOf} onChange={setBestOf} />
      <Field label="When" optional type="datetime-local" value={playAt} onChange={(e) => setPlayAt(e.target.value)} hint="Leave empty for next time you meet." />
      <Field label="Where" optional maxLength={120} value={place} onChange={(e) => setPlace(e.target.value)} />
      <Field label="Message" optional maxLength={300} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Loser buys the sodas?" />
      {stakes && (
        <>
          <ChoiceGroup
            legend="Your pledge if you lose"
            columns={3}
            options={[
              { value: "none" as const, label: "No stake" },
              { value: "money" as const, label: "An amount" },
              { value: "thing" as const, label: "Something" },
            ]}
            value={stakeKind}
            onChange={setStakeKind}
          />
          {stakeKind === "money" && <Field label="Amount (KES)" type="number" min={1} inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} error={errors.stake_minor} />}
          {stakeKind === "thing" && <Field label="What" maxLength={60} value={thing} onChange={(e) => setThing(e.target.value)} placeholder="A soda" error={errors.stake_note} />}
          <p className="text-sm text-muted-foreground">Only the two of you see a pledge. Coast TT records it but never collects or pays anything.</p>
        </>
      )}
      {save.isError && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <DraftBar draft={draft} />
      <div className="flex gap-2">
        <Button type="submit" disabled={!opponent.length || save.isPending}>
          {save.isPending ? "Sending…" : "Send challenge"}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function ChallengeCard({ challenge: c }: { challenge: Challenge }) {
  const queryClient = useQueryClient()
  const [counterAt, setCounterAt] = useState("")
  const [reason, setReason] = useState("")
  const [games, setGames] = useState<string[][]>([["", ""]])
  const run = useMutation({
    mutationFn: (step: () => Promise<Challenge>) => step(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sodaKeys.all }),
  })
  const other = opponentOf(c)
  const me = c.mine === "challenger" ? "challenger" : "challenged"
  const staked = stakeText(c)
  const outcome = c.outcome as { state: string; winner_id: string | null; owed_by_id?: string | null }
  const iWon = outcome.winner_id && outcome.winner_id !== other.id
  const iOwe = outcome.owed_by_id && outcome.owed_by_id !== other.id
  const theyOwe = outcome.owed_by_id && outcome.owed_by_id === other.id
  const result = c.result as { games: number[][]; challenger_confirmed: boolean; challenged_confirmed: boolean; disputed: boolean; dispute_reason: string } | null
  const myConfirmed = result ? (me === "challenger" ? result.challenger_confirmed : result.challenged_confirmed) : false
  // Scores are entered from the viewer's side and sent from the challenger's.
  const toChallenger = (rows: string[][]) => rows.filter((g) => g[0] !== "" && g[1] !== "").map(([mine, theirs]) => (me === "challenger" ? [Number(mine), Number(theirs)] : [Number(theirs), Number(mine)]))
  const shown = (g: number[]) => (me === "challenger" ? g : [g[1], g[0]])
  const sharing = me === "challenger" ? c.challenger_shares : c.challenged_shares

  return (
    <article className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-bold">
          {me === "challenger" ? "You" : other.display_name} v {me === "challenger" ? other.display_name : "you"}
        </h3>
        <span className="text-sm font-semibold text-muted-foreground">{STATUS_LABEL[c.status]}</span>
      </div>
      <p className="text-sm">
        {c.format === "doubles" ? "Doubles" : "Singles"} · best of {c.best_of} · {when(c.play_at)}
        {c.place && ` · ${c.place}`}
      </p>
      {c.status === "countered" && c.proposed_at && <p className="text-sm font-semibold">Proposed instead: {when(c.proposed_at)}</p>}
      {c.message && <p className="italic">"{c.message}"</p>}
      {staked && (
        <p className="text-sm">
          Pledge: {staked} from {me === "challenger" ? "you" : other.display_name}
          {c.challenged_staked && ` and ${me === "challenged" ? "you" : other.display_name}`}
        </p>
      )}
      {result && (
        <p className="tabular-nums">
          Games: {result.games.map((g) => shown(g).join("–")).join(", ")}
          {result.disputed && <span className="font-semibold"> · disputed: {result.dispute_reason}</span>}
        </p>
      )}
      {outcome.state === "confirmed" || outcome.state === "settled" ? (
        <p className="font-semibold">
          {iWon ? "You won" : `${other.display_name} won`}
          {iOwe && ` · you pledged ${staked}`}
          {theyOwe && ` · ${other.display_name} pledged ${staked}`}
          {outcome.state === "settled" && " · settled"}
        </p>
      ) : null}
      {outcome.state === "disputed" && <p className="text-sm">Nothing is owed while the result is disputed. Record it again once you agree.</p>}
      {run.isError && <FormAlert>{errorMessage(run.error)}</FormAlert>}

      <div className="flex flex-wrap gap-2">
        {me === "challenged" && c.status === "pending" && (
          <>
            <Button disabled={run.isPending} onClick={() => run.mutate(() => acceptChallenge(c.id, false))}>
              Accept{staked ? " without staking" : ""}
            </Button>
            {staked && (
              <Button variant="outline" disabled={run.isPending} onClick={() => run.mutate(() => acceptChallenge(c.id, true))}>
                Accept and match {staked}
              </Button>
            )}
            <Button variant="ghost" disabled={run.isPending} onClick={() => run.mutate(() => declineChallenge(c.id))}>
              Decline
            </Button>
          </>
        )}
        {me === "challenger" && c.status === "countered" && (
          <Button disabled={run.isPending} onClick={() => run.mutate(() => acceptChallenge(c.id, false))}>
            Take the new time
          </Button>
        )}
        {me === "challenger" && (c.status === "pending" || c.status === "countered") && (
          <Button variant="ghost" disabled={run.isPending} onClick={() => run.mutate(() => withdrawChallenge(c.id))}>
            Withdraw
          </Button>
        )}
        {result && !result.disputed && !myConfirmed && (
          <>
            <Button disabled={run.isPending} onClick={() => run.mutate(() => confirmResult(c.id))}>
              Confirm result
            </Button>
            <Button variant="outline" disabled={run.isPending || !reason.trim()} onClick={() => run.mutate(() => disputeResult(c.id, reason.trim()))}>
              Dispute
            </Button>
          </>
        )}
        {iWon && outcome.owed_by_id && outcome.state === "confirmed" && (
          <Button variant="outline" disabled={run.isPending} onClick={() => run.mutate(() => settlePledge(c.id))}>
            Mark pledge settled
          </Button>
        )}
        {(c.status === "accepted" || c.status === "played") && (
          <Button variant="ghost" aria-pressed={sharing} disabled={run.isPending} onClick={() => run.mutate(() => shareChallenge(c.id, !sharing))}>
            {sharing ? "Stop sharing with my club" : "Share with my club"}
          </Button>
        )}
      </div>

      {me === "challenged" && c.status === "pending" && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Propose another time" type="datetime-local" className="min-w-56" value={counterAt} onChange={(e) => setCounterAt(e.target.value)} />
          <Button variant="outline" disabled={!counterAt || run.isPending} onClick={() => run.mutate(() => counterChallenge(c.id, fromZonedInput(counterAt, LOCAL_TIME_ZONE) ?? ""))}>
            Propose
          </Button>
        </div>
      )}
      {result && !result.disputed && !myConfirmed && <Field label="If you dispute it, why" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />}
      {(c.status === "accepted" || (c.status === "played" && (result?.disputed || !myConfirmed))) && (
        <fieldset className="flex flex-col gap-2 rounded-lg border p-3">
          <legend className="px-1 font-semibold">{result ? "Record it again" : "Record the result"}</legend>
          <p className="text-sm text-muted-foreground">Your points first, then {other.display_name}'s.</p>
          {games.map((g, i) => (
            <div key={i} className="flex items-end gap-2">
              <Field label={`Game ${i + 1}: you`} type="number" min={0} max={99} inputMode="numeric" className="w-28" value={g[0]} onChange={(e) => setGames(games.map((row, j) => (j === i ? [e.target.value, row[1]] : row)))} />
              <Field label={other.display_name} type="number" min={0} max={99} inputMode="numeric" className="w-28" value={g[1]} onChange={(e) => setGames(games.map((row, j) => (j === i ? [row[0], e.target.value] : row)))} />
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            {games.length < c.best_of && (
              <Button type="button" variant="ghost" onClick={() => setGames([...games, ["", ""]])}>
                Add a game
              </Button>
            )}
            <Button disabled={run.isPending || toChallenger(games).length === 0} onClick={() => run.mutate(() => recordResult(c.id, toChallenger(games)))}>
              Save result
            </Button>
          </div>
        </fieldset>
      )}
    </article>
  )
}
