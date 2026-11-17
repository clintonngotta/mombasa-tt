import { useState, type FormEvent } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { fromZonedInput, toZonedInput } from "@/lib/dates"
import {
  canManageTournament,
  createEvent,
  deleteEvent,
  getTournament,
  tournamentKeys,
  updateEvent,
  type BestOf,
  type EventFormat,
  type EventKind,
  type Seeding,
  type Tournament,
  type TournamentEvent,
  isClosed,
} from "@/lib/tournaments"

const KINDS: { value: EventKind; label: string; description: string }[] = [
  { value: "singles", label: "Singles", description: "One player per entry" },
  { value: "doubles", label: "Doubles", description: "Two players per entry" },
  { value: "team", label: "Teams", description: "A roster and a captain" },
]

const FORMATS: { value: EventFormat; label: string; description: string }[] = [
  { value: "knockout", label: "Knockout", description: "Lose once and you're out" },
  { value: "round_robin", label: "Round robin", description: "Everyone plays everyone" },
  { value: "groups_knockout", label: "Groups, then knockout", description: "Group winners go through" },
]

const BEST_OF: { value: `${BestOf}`; label: string }[] = [
  { value: "3", label: "Best of 3" },
  { value: "5", label: "Best of 5" },
  { value: "7", label: "Best of 7" },
]

const SEEDINGS: { value: Seeding; label: string; description: string }[] = [
  { value: "rating", label: "By rating", description: "Highest rated first" },
  { value: "manual", label: "By staff", description: "You set the order" },
  { value: "none", label: "Unseeded", description: "Drawn at random" },
]

const whole = (text: string) => (text.trim() === "" ? null : Number(text))

/** Add an event to a tournament or change its set-up (REQ-007). */
export function EventFormPage() {
  const { id = "", eventId } = useParams()
  const { query: memberships, results: all } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const t = tournament.data
  const event = eventId ? t?.events.find((e) => e.id === eventId) : undefined
  const allowed = !!t && canManageTournament(all, t)
  const closed = !!t && (isClosed(t) || (!!event && isClosed(event)))

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">{eventId ? (event?.name ?? "Event") : "New event"}</h1>
      {tournament.isPending && <p className="text-muted-foreground">Loading…</p>}
      {tournament.isError && <FormAlert>{errorMessage(tournament.error, "We couldn't load this tournament.")}</FormAlert>}
      {t && memberships.isSuccess && !allowed && <AccessLost />}
      {t && eventId && !event && <FormAlert>This event no longer exists.</FormAlert>}
      {closed && <FormAlert>This event is over and can't be changed.</FormAlert>}
      {t && allowed && !closed && (!eventId || event) && <EventForm key={event?.id ?? "new"} tournament={t} event={event} />}
    </div>
  )
}

function EventForm({ tournament: t, event }: { tournament: Tournament; event?: TournamentEvent }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const frozen = !!event && event.status !== "scheduled"
  const [name, setName] = useState(event?.name ?? "")
  const [kind, setKind] = useState<EventKind | "">(event?.kind ?? "")
  const [format, setFormat] = useState<EventFormat | "">(event?.format ?? "")
  const [groups, setGroups] = useState(event?.group_count?.toString() ?? "")
  const [qualifiers, setQualifiers] = useState(event?.qualifiers_per_group?.toString() ?? "")
  const [capacity, setCapacity] = useState(event?.capacity?.toString() ?? "")
  const [bestOf, setBestOf] = useState<`${BestOf}`>(`${event?.best_of ?? 5}`)
  const [rest, setRest] = useState((event?.rest_minutes ?? 10).toString())
  const [seeding, setSeeding] = useState<Seeding>(event?.seeding ?? "rating")
  const [fee, setFee] = useState(event && event.entry_fee.amount_minor > 0 ? (event.entry_fee.amount_minor / 100).toString() : "")
  const [opens, setOpens] = useState(toZonedInput(event?.registration_opens_at ?? null, t.timezone))
  const [closes, setCloses] = useState(toZonedInput(event?.registration_closes_at ?? null, t.timezone))
  const [confirmRemove, setConfirmRemove] = useState(false)
  const currency = event?.entry_fee.currency ?? "KES"

  const done = (fresh: Tournament) => {
    queryClient.setQueryData(tournamentKeys.detail(t.id), fresh)
    void queryClient.invalidateQueries({ queryKey: tournamentKeys.all, refetchType: "active" })
    navigate(`/tournaments/${t.id}`)
  }

  const save = useMutation({
    mutationFn: () => {
      const details = {
        name: name.trim(),
        capacity: whole(capacity),
        rest_minutes: whole(rest) ?? 10,
        entry_fee: { amount_minor: Math.round((Number(fee) || 0) * 100), currency },
        registration_opens_at: fromZonedInput(opens, t.timezone),
        registration_closes_at: fromZonedInput(closes, t.timezone),
      }
      // A started event's structure is fixed, so it isn't sent at all.
      const structure = {
        kind: kind as EventKind,
        format: format as EventFormat,
        best_of: Number(bestOf) as BestOf,
        seeding,
        ...(format === "groups_knockout" ? { group_count: whole(groups), qualifiers_per_group: whole(qualifiers) } : {}),
      }
      if (event) return updateEvent(t.id, event.id, frozen ? details : { ...details, ...structure })
      return createEvent(t.id, { ...details, ...structure })
    },
    onSuccess: done,
  })
  const remove = useMutation({ mutationFn: () => deleteEvent(t.id, event!.id), onSuccess: done })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }

  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <Field label="Name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} hint="For example Men's singles or Open doubles" />

      {frozen ? (
        <p role="status" className="rounded-lg border bg-muted p-3 text-sm">
          This event has started, so who enters, the format, best of, seeding, groups and qualifiers are fixed. You can still change the details below.
        </p>
      ) : (
        <>
          <ChoiceGroup legend="Who enters" columns={3} options={KINDS} value={kind} onChange={setKind} error={errors.kind} />
          <ChoiceGroup legend="Format" columns={3} options={FORMATS} value={format} onChange={setFormat} error={errors.format} />
          {format === "groups_knockout" && (
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Groups" type="number" inputMode="numeric" min={2} required value={groups} onChange={(e) => setGroups(e.target.value)} error={errors.group_count} />
              <Field
                label="Through from each group"
                type="number"
                inputMode="numeric"
                min={1}
                required
                value={qualifiers}
                onChange={(e) => setQualifiers(e.target.value)}
                error={errors.qualifiers_per_group}
              />
            </div>
          )}
          <ChoiceGroup legend="Match length" columns={3} options={BEST_OF} value={bestOf} onChange={setBestOf} error={errors.best_of} />
          <ChoiceGroup legend="Seeding" columns={3} options={SEEDINGS} value={seeding} onChange={setSeeding} error={errors.seeding} />
        </>
      )}

      <div className="grid gap-5 sm:grid-cols-2">
        <Field
          label="Entry limit"
          optional
          type="number"
          inputMode="numeric"
          min={2}
          value={capacity}
          onChange={(e) => setCapacity(e.target.value)}
          error={errors.capacity}
          hint="Leave empty for no limit."
        />
        <Field
          label="Rest between matches (minutes)"
          type="number"
          inputMode="numeric"
          min={0}
          value={rest}
          onChange={(e) => setRest(e.target.value)}
          error={errors.rest_minutes}
        />
      </div>
      <Field
        label={`Entry fee (${currency})`}
        optional
        type="number"
        inputMode="decimal"
        min={0}
        step="0.01"
        value={fee}
        onChange={(e) => setFee(e.target.value)}
        error={errors.entry_fee}
        hint="Shown to players as information. mombasa-tt doesn't collect payments."
      />
      <div className="grid gap-5 sm:grid-cols-2">
        <Field
          label="Registration opens"
          optional
          type="datetime-local"
          value={opens}
          onChange={(e) => setOpens(e.target.value)}
          error={errors.registration_opens_at}
        />
        <Field
          label="Registration closes"
          optional
          type="datetime-local"
          min={opens || undefined}
          value={closes}
          onChange={(e) => setCloses(e.target.value)}
          error={errors.registration_closes_at}
        />
      </div>
      <p className="text-sm text-muted-foreground">Times are venue local ({t.timezone}).</p>

      {save.isError && Object.keys(errors).length === 0 && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Button type="submit" size="lg" disabled={save.isPending}>
        {save.isPending ? "Saving…" : event ? "Save event" : "Add event"}
      </Button>

      {event && t.status === "draft" && (
        <section aria-label="Remove event" className="flex flex-col gap-2 border-t pt-4">
          {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
          {confirmRemove ? (
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex-1 text-sm">Remove {event.name} from this draft?</p>
              <Button type="button" variant="outline" onClick={() => setConfirmRemove(false)}>
                Keep
              </Button>
              <Button type="button" variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
                {remove.isPending ? "Removing…" : "Remove event"}
              </Button>
            </div>
          ) : (
            <Button type="button" variant="ghost" className="self-start text-destructive" onClick={() => setConfirmRemove(true)}>
              Remove event
            </Button>
          )}
        </section>
      )}
    </form>
  )
}
