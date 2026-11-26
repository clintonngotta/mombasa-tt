import { useMemo, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { Segmented } from "@/components/forms/Segmented"
import { Toggle } from "@/components/forms/Toggle"
import { ApiError, errorMessage } from "@/lib/api"
import { dayOf, formatDay, formatInstant, fromZonedInput, toZonedInput } from "@/lib/dates"
import {
  MOVE_REASON_LABEL,
  clearNotBefore,
  getOrderOfPlay,
  moveMatchLater,
  orderKeys,
  saveStages,
  setNotBefore,
  setRelease,
  type MoveReason,
  type OrderOfPlay,
  type OrderSlot,
  type Stage,
} from "@/lib/orderOfPlay"
import { scheduleKeys } from "@/lib/schedule"
import { getTournament, tournamentKeys } from "@/lib/tournaments"

const ALL = ""

const clock = (iso: string, timeZone: string) =>
  new Intl.DateTimeFormat("en-KE", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso))

/**
 * The order of play (REQ-053, user request 2026-11-22): every planned match by day, time and table, and
 * the order of the stages. Everybody who sees the tournament sees it once it is out; staff see it from
 * publication and choose when it goes out, set a player's "not before" and move a match later.
 */
export function OrderOfPlayPage() {
  const { id = "" } = useParams()
  const [params, setParams] = useSearchParams()
  const eventFilter = params.get("event") ?? ALL
  const [mineOnly, setMineOnly] = useState(false)
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const order = useQuery({ queryKey: orderKeys.detail(id), queryFn: () => getOrderOfPlay(id), staleTime: 0, refetchInterval: 60_000 })
  const failed = tournament.error ?? order.error
  const missing = failed instanceof ApiError && failed.status === 404
  const zone = tournament.data?.timezone ?? "Africa/Nairobi"
  const data = order.data
  const slots = useMemo(
    () => (data?.slots ?? []).filter((slot) => (eventFilter === ALL || slot.event_id === eventFilter) && (!mineOnly || slot.mine)),
    [data, eventFilter, mineOnly],
  )
  const events = useMemo(() => {
    const seen = new Map<string, string>()
    for (const slot of data?.slots ?? []) seen.set(slot.event_id, slot.event_name)
    return [...seen]
  }, [data])
  const days = useMemo(() => {
    const byDay = new Map<string, OrderSlot[]>()
    for (const slot of slots) {
      const day = dayOf(slot.scheduled_at, zone)
      byDay.set(day, [...(byDay.get(day) ?? []), slot])
    }
    return [...byDay]
  }, [slots, zone])

  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{tournament.data?.name ?? "Tournament"}</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Order of play</h1>
      {missing && <FormAlert>This tournament doesn't exist or hasn't been published.</FormAlert>}
      {failed && !missing && <FormAlert>{errorMessage(failed, "We couldn't load the order of play.")}</FormAlert>}
      {order.isPending && !failed && <p className="text-muted-foreground">Loading the order of play…</p>}

      {data && <Status data={data} zone={zone} tournamentId={id} />}

      {data && data.slots.length > 0 && (
        <div className="flex flex-wrap items-end gap-3">
          {events.length > 1 && (
            <div className="min-w-[220px]">
              <SelectField
                label="Event"
                value={eventFilter}
                onChange={(value) => setParams(value ? { event: value } : {}, { replace: true })}
                options={[{ value: ALL, label: "Every event" }, ...events.map(([value, label]) => ({ value, label }))]}
              />
            </div>
          )}
          {data.slots.some((slot) => slot.mine) && (
            <Button variant={mineOnly ? "default" : "outline"} aria-pressed={mineOnly} onClick={() => setMineOnly(!mineOnly)}>
              {mineOnly ? "Showing my matches" : "Only my matches"}
            </Button>
          )}
        </div>
      )}

      {days.map(([day, rows]) => (
        <section key={day} aria-labelledby={`day-${day}`} className="flex flex-col gap-2">
          <h2 id={`day-${day}`} className="text-2xl font-bold">
            {formatDay(day)}
          </h2>
          <ol className="flex flex-col gap-2">
            {rows.map((slot) => (
              <SlotRow key={slot.match_id} slot={slot} zone={zone} tournamentId={id} manage={data?.can_manage ?? false} />
            ))}
          </ol>
        </section>
      ))}
      {data && data.slots.length > 0 && slots.length === 0 && <p className="text-muted-foreground">No match matches that choice.</p>}

      {data && data.stages.length > 0 && (data.can_manage ? <StageEditor tournamentId={id} stages={data.stages} /> : <StageList stages={data.stages} />)}
      {data?.can_manage && data.published && <NotBeforeEditor tournamentId={id} data={data} zone={zone} />}
    </div>
  )
}

function useKeep(tournamentId: string) {
  const queryClient = useQueryClient()
  return (fresh: OrderOfPlay) => {
    queryClient.setQueryData(orderKeys.detail(tournamentId), fresh)
    void queryClient.invalidateQueries({ queryKey: scheduleKeys.detail(tournamentId) })
  }
}

function Status({ data, zone, tournamentId }: { data: OrderOfPlay; zone: string; tournamentId: string }) {
  if (!data.published) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
        <p>The order of play isn't published yet.</p>
        {data.can_manage && (
          <>
            <p className="text-sm text-muted-foreground">
              Plan times and tables in the schedule and publish it. It goes public no earlier than three days before play starts ({formatInstant(data.earliest_release, zone)}), and you can choose any time up to the start.
            </p>
            <Link to={`/tournaments/${tournamentId}/schedule-plan`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
              Plan the schedule
            </Link>
          </>
        )}
      </div>
    )
  }
  if (!data.released && !data.can_manage) {
    return (
      <p className="rounded-xl border bg-card p-4">
        The order of play comes out {data.release_at ? formatInstant(data.release_at, zone) : "before play starts"}. Every player entered is told when it does.
      </p>
    )
  }
  if (!data.can_manage) return null
  return <ReleaseControl data={data} zone={zone} tournamentId={tournamentId} />
}

function ReleaseControl({ data, zone, tournamentId }: { data: OrderOfPlay; zone: string; tournamentId: string }) {
  const keep = useKeep(tournamentId)
  const [when, setWhen] = useState(toZonedInput(data.release_at, zone))
  const save = useMutation({ mutationFn: (at: string | null) => setRelease(tournamentId, at), onSuccess: keep })
  if (data.released) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
        <p className="font-semibold">Public since {data.release_at ? formatInstant(data.release_at, zone) : "it was published"}.</p>
        <p className="text-sm text-muted-foreground">Changes you publish now reach everyone, and the players and umpires of moved matches are told.</p>
        <Link to={`/tournaments/${tournamentId}/schedule-plan`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
          Edit the schedule
        </Link>
      </div>
    )
  }
  return (
    <section aria-labelledby="release-heading" className="flex flex-col gap-3 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <h2 id="release-heading" className="text-xl font-bold">
        Only staff see this until {data.release_at ? formatInstant(data.release_at, zone) : "it goes public"}
      </h2>
      <p className="text-sm text-muted-foreground">
        Choose when it goes public: from {formatInstant(data.earliest_release, zone)} (three days before play starts) up to the start at {formatInstant(data.starts_at, zone)}. Every player entered is told then. Changes before that are nobody's news.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[240px]">
          <Field label="Goes public at" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </div>
        <Button disabled={save.isPending || !when} onClick={() => save.mutate(fromZonedInput(when, zone))}>
          Save time
        </Button>
        <Button variant="outline" disabled={save.isPending} onClick={() => save.mutate(null)}>
          Publish now
        </Button>
      </div>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Link to={`/tournaments/${tournamentId}/schedule-plan`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
        Edit the schedule
      </Link>
    </section>
  )
}

function SlotRow({ slot, zone, tournamentId, manage }: { slot: OrderSlot; zone: string; tournamentId: string; manage: boolean }) {
  const [moving, setMoving] = useState(false)
  const status = slot.status === "scheduled" ? (slot.on_table ? "On the table" : "") : slot.status === "completed" ? "Played" : slot.status.replace("_", " ")
  const canMove = manage && slot.status === "scheduled" && !slot.on_table
  return (
    <li className={`flex flex-col gap-2 rounded-xl border p-3 ${slot.mine ? "border-brand-blue bg-surface-selected" : "bg-card"}`}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="w-14 text-lg font-bold tabular-nums">{clock(slot.scheduled_at, zone)}</span>
        <span className="w-24 text-sm font-semibold">{slot.table || "Table to come"}</span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-semibold break-words">{slot.title}</span>
          <span className="text-sm text-muted-foreground">{slot.label}</span>
        </span>
        {slot.mine && <span className="text-sm font-semibold text-brand-blue">Your match</span>}
        {status && <span className="text-sm text-muted-foreground capitalize">{status}</span>}
        {canMove && !moving && (
          <Button variant="outline" aria-label={`Move ${slot.title} later`} onClick={() => setMoving(true)}>
            Move later
          </Button>
        )}
      </div>
      {moving && <MoveForm slot={slot} zone={zone} tournamentId={tournamentId} onDone={() => setMoving(false)} />}
    </li>
  )
}

function MoveForm({ slot, zone, tournamentId, onDone }: { slot: OrderSlot; zone: string; tournamentId: string; onDone: () => void }) {
  const keep = useKeep(tournamentId)
  const [when, setWhen] = useState(toZonedInput(new Date(new Date(slot.scheduled_at).getTime() + 60 * 60_000).toISOString(), zone))
  const [reason, setReason] = useState<MoveReason>("player_request")
  const [note, setNote] = useState("")
  const move = useMutation({
    mutationFn: () => moveMatchLater(tournamentId, slot.match_id, fromZonedInput(when, zone) ?? "", reason, note),
    onSuccess: (fresh) => {
      keep(fresh)
      onDone()
    },
  })
  return (
    <form
      className="flex flex-col gap-3 border-t pt-3"
      onSubmit={(e) => {
        e.preventDefault()
        move.mutate()
      }}
    >
      <p className="text-sm text-muted-foreground">Published at once. Matches that would then clash on its table or with its players move on too.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="New start" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required />
        <Field label="Note for the players" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} optional />
      </div>
      <Segmented label="Why" value={reason} onChange={setReason} options={(Object.keys(MOVE_REASON_LABEL) as MoveReason[]).map((value) => ({ value, label: MOVE_REASON_LABEL[value] }))} />
      {move.isError && <FormAlert>{errorMessage(move.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={move.isPending || !when}>
          Move it
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Back
        </Button>
      </div>
    </form>
  )
}

function StageList({ stages }: { stages: Stage[] }) {
  return (
    <section aria-labelledby="stages-heading" className="flex flex-col gap-2">
      <h2 id="stages-heading" className="text-2xl font-bold">
        Stages in order
      </h2>
      <ol className="flex list-decimal flex-col gap-1 pl-6">
        {stages.map((stage) => (
          <li key={`${stage.event_id}-${stage.stage}`}>{stage.label}</li>
        ))}
      </ol>
    </section>
  )
}

function StageEditor({ tournamentId, stages }: { tournamentId: string; stages: Stage[] }) {
  const keep = useKeep(tournamentId)
  const [draft, setDraft] = useState<Stage[] | null>(null)
  const shown = draft ?? stages
  const save = useMutation({
    mutationFn: () => saveStages(tournamentId, shown.map(({ event_id, stage }) => ({ event_id, stage }))),
    onSuccess: (fresh) => {
      keep(fresh)
      setDraft(null)
    },
  })
  const swap = (index: number, other: number) => {
    const next = [...shown]
    ;[next[index], next[other]] = [next[other], next[index]]
    setDraft(next)
  }
  const saved = stages.every((stage) => stage.placed)
  return (
    <section aria-labelledby="stages-heading" className="flex flex-col gap-3">
      <h2 id="stages-heading" className="text-2xl font-bold">
        Stages in order
      </h2>
      <p className="text-sm text-muted-foreground">
        The control centre sends matches of the first stage first. When none of its matches can go (players busy or resting), a free table takes the next stage's match instead of standing idle.
        {!saved && " This order isn't saved yet: until you save it, matches go by planned time."}
      </p>
      <ol className="flex flex-col gap-2">
        {shown.map((stage, index) => (
          <li key={`${stage.event_id}-${stage.stage}`} className="flex items-center justify-between gap-2 rounded-xl border bg-card p-3">
            <span>
              <span className="mr-2 font-bold tabular-nums">{index + 1}.</span>
              {stage.label}
            </span>
            <span className="flex gap-1">
              <Button variant="outline" size="icon" aria-label={`Move ${stage.label} up`} disabled={index === 0} onClick={() => swap(index, index - 1)}>
                <ArrowUp aria-hidden className="size-4" />
              </Button>
              <Button variant="outline" size="icon" aria-label={`Move ${stage.label} down`} disabled={index === shown.length - 1} onClick={() => swap(index, index + 1)}>
                <ArrowDown aria-hidden className="size-4" />
              </Button>
            </span>
          </li>
        ))}
      </ol>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Button className="self-start" disabled={save.isPending || (saved && draft === null)} onClick={() => save.mutate()}>
        Save the order
      </Button>
    </section>
  )
}

function NotBeforeEditor({ tournamentId, data, zone }: { tournamentId: string; data: OrderOfPlay; zone: string }) {
  const keep = useKeep(tournamentId)
  const firstDay = dayOf(data.starts_at, zone)
  const [player, setPlayer] = useState("")
  const [when, setWhen] = useState(`${firstDay}T11:00`)
  const [note, setNote] = useState("")
  const [move, setMove] = useState(true)
  const save = useMutation({
    mutationFn: () => setNotBefore(tournamentId, player, fromZonedInput(when, zone) ?? "", note, move),
    onSuccess: (fresh) => {
      keep(fresh)
      setPlayer("")
      setNote("")
    },
  })
  const clear = useMutation({ mutationFn: (userId: string) => clearNotBefore(tournamentId, userId), onSuccess: keep })
  return (
    <section aria-labelledby="not-before-heading" className="flex flex-col gap-3">
      <h2 id="not-before-heading" className="text-2xl font-bold">
        Players starting later
      </h2>
      <p className="text-sm text-muted-foreground">
        A player with somewhere to be first: none of their matches is planned or sent to a table before their time. The control centre holds their match until then unless you send it anyway, with a reason.
      </p>
      {data.not_before.length > 0 && (
        <ul className="flex flex-col gap-2">
          {data.not_before.map((row) => (
            <li key={row.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card p-3">
              <span className="flex flex-col">
                <span className="font-semibold">
                  {row.display_name}: not before {formatInstant(row.at, zone)}
                </span>
                {row.note && <span className="text-sm text-muted-foreground">{row.note}</span>}
              </span>
              <Button variant="outline" disabled={clear.isPending} aria-label={`${row.display_name} may play at any time`} onClick={() => clear.mutate(row.user_id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      {clear.isError && <FormAlert>{errorMessage(clear.error)}</FormAlert>}
      <form
        className="flex flex-col gap-3 rounded-xl border bg-card p-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <h3 className="font-bold">Set a start time for a player</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField
            label="Player"
            value={player}
            onChange={setPlayer}
            placeholder="Choose a player"
            options={data.players.map((p) => ({ value: p.id, label: p.display_name }))}
          />
          <Field label="Not before" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required />
        </div>
        <Field label="Reason" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} optional hint="Shown to staff only." />
        <Toggle
          checked={move}
          onChange={setMove}
          label="Move their published matches now"
          description="Their matches planned earlier move to this time and are published at once, with the matches that then clash. Once the order of play is out, the people affected are told."
        />
        {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
        <Button type="submit" className="self-start" disabled={save.isPending || !player || !when}>
          Save
        </Button>
      </form>
    </section>
  )
}
