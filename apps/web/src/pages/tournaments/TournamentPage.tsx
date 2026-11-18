import { useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, Clock, MapPin, Pencil, Plus, Users } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { EventStatusChip, TournamentStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { formatDayRange, formatInstant } from "@/lib/dates"
import { entryBlock, placesTaken } from "@/lib/entries"
import {
  ACTION_LABEL,
  cancelEvent,
  cancelTournament,
  canManageTournament,
  countdown,
  deleteTournament,
  eventSummary,
  eventTabPath,
  firstTab,
  formatFee,
  getTournament,
  getTournamentHistory,
  moveEvent,
  moveTournament,
  SEEDING_LABEL,
  tournamentKeys,
  type EventAction,
  type Tournament,
  type TournamentAction,
  type TournamentEvent,
  isClosed,
} from "@/lib/tournaments"

/** One tournament (REQ-007): what everyone sees, plus the controls of the host's competition staff. */
export function TournamentPage() {
  const { id = "" } = useParams()
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const t = tournament.data
  const staff = !!t && canManageTournament(memberships, t)
  const missing = tournament.error instanceof ApiError && tournament.error.status === 404

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/play">Play</BackLink>
      {tournament.isPending && <p className="text-muted-foreground">Loading tournament…</p>}
      {missing && <FormAlert>This tournament doesn't exist or hasn't been published.</FormAlert>}
      {tournament.isError && !missing && <FormAlert>{errorMessage(tournament.error, "We couldn't load this tournament.")}</FormAlert>}
      {t && (
        <>
          <Overview tournament={t} />
          <Events tournament={t} staff={staff} />
          {staff && <Manage tournament={t} />}
        </>
      )}
    </div>
  )
}

function Overview({ tournament: t }: { tournament: Tournament }) {
  const soon = countdown(t)
  return (
    <header className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 className="min-w-0 text-[32px] leading-9 font-bold break-words">{t.name}</h1>
        <TournamentStatusChip status={t.status} />
      </div>
      <dl className="flex flex-col gap-2">
        <Fact icon={<CalendarDays aria-hidden className="size-5" />} label="Dates">
          {formatDayRange(t.starts_on, t.ends_on)}
          {soon && <span className="font-semibold text-brand-blue"> · {soon}</span>}
        </Fact>
        <Fact icon={<MapPin aria-hidden className="size-5" />} label="Venue">
          {t.venue ? [t.venue.name, t.venue.address, t.venue.town].filter(Boolean).join(", ") : "Venue to be announced"}
        </Fact>
        <Fact icon={<Users aria-hidden className="size-5" />} label="Host">
          {t.organization.name}, {t.organization.town}
        </Fact>
      </dl>
      {t.status === "cancelled" && <FormAlert>Cancelled: {t.cancel_reason}</FormAlert>}
      {t.description && <p className="whitespace-pre-line">{t.description}</p>}
      <p className="text-sm text-muted-foreground">Dates and times are venue local ({t.timezone}).</p>
    </header>
  )
}

function Fact({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <dt className="mt-0.5 text-muted-foreground">
        {icon}
        <span className="sr-only">{label}</span>
      </dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

/** What the mutations on this page do afterwards: put the fresh tournament in the cache and refresh lists. */
function useTournamentChange(id: string) {
  const queryClient = useQueryClient()
  return (fresh: Tournament) => {
    queryClient.setQueryData(tournamentKeys.detail(id), fresh)
    void queryClient.invalidateQueries({ queryKey: tournamentKeys.all, refetchType: "active" })
  }
}

function Events({ tournament: t, staff }: { tournament: Tournament; staff: boolean }) {
  const open = !isClosed(t)
  return (
    <section aria-labelledby="events-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="events-heading" className="text-2xl font-bold">
          Events
        </h2>
        {staff && open && (
          <Link to={`/tournaments/${t.id}/events/new`} className={buttonVariants({ variant: "outline" })}>
            <Plus aria-hidden className="size-5" /> Add event
          </Link>
        )}
      </div>
      {t.events.length === 0 && <p className="text-muted-foreground">{staff ? "No events yet. Add the first one to publish." : "No events yet."}</p>}
      <ul className="flex flex-col gap-3">
        {t.events.map((event) => (
          <li key={event.id}>
            <EventCard tournament={t} event={event} staff={staff && open} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function EventCard({ tournament: t, event, staff }: { tournament: Tournament; event: TournamentEvent; staff: boolean }) {
  const onChange = useTournamentChange(t.id)
  const [cancelling, setCancelling] = useState(false)
  const move = useMutation({ mutationFn: (action: EventAction) => moveEvent(t.id, event.id, action), onSuccess: onChange })
  const cancel = useMutation({
    mutationFn: (reason: string) => cancelEvent(t.id, event.id, reason),
    onSuccess: (fresh) => {
      setCancelling(false)
      onChange(fresh)
    },
  })
  const closed = isClosed(event)
  const facts = [
    event.capacity ? `Up to ${event.capacity} entries` : "No entry limit",
    `Entry fee: ${formatFee(event.entry_fee)}`,
    SEEDING_LABEL[event.seeding],
    `${event.rest_minutes} min rest between matches`,
  ]

  return (
    <article aria-label={event.name} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <h3 className="text-xl font-bold break-words">{event.name}</h3>
          <p className="text-sm text-muted-foreground">{eventSummary(event)}</p>
        </div>
        <EventStatusChip status={event.status} />
      </div>
      <p className="text-sm">{facts.join(" · ")}</p>
      {(event.registration_opens_at || event.registration_closes_at) && (
        <p className="flex items-start gap-1.5 text-sm text-muted-foreground">
          <Clock aria-hidden className="mt-0.5 size-4 shrink-0" />
          <span>
            {event.registration_opens_at && <>Registration opens {formatInstant(event.registration_opens_at, t.timezone)}. </>}
            {event.registration_closes_at && <>Closes {formatInstant(event.registration_closes_at, t.timezone)}.</>}
          </span>
        </p>
      )}
      {event.status === "cancelled" && <p className="text-sm font-semibold text-destructive">Cancelled: {event.cancel_reason}</p>}
      {t.status !== "draft" && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold">{placesTaken(event)}</p>
          <div className="flex flex-wrap gap-2">
            {staff && (
              <Link to={`/tournaments/${t.id}/events/${event.id}/draw`} aria-label={`Draw desk for ${event.name}`} className={buttonVariants({ variant: "outline" })}>
                Draw desk
              </Link>
            )}
            <Link to={eventTabPath(t.id, event.id, firstTab(event.format))} aria-label={`Draw and results for ${event.name}`} className={buttonVariants({ variant: "outline" })}>
              Draw and results
            </Link>
            <Link to={`/tournaments/${t.id}/events/${event.id}/entries`} aria-label={`Entries for ${event.name}`} className={buttonVariants({ variant: entryBlock(t, event) ? "outline" : "default" })}>
              {entryBlock(t, event) ? "See entries" : "Enter or see entries"}
            </Link>
          </div>
        </div>
      )}

      {staff && !closed && (
        <div className="flex flex-col gap-2 border-t pt-3">
          {move.isError && <FormAlert>{errorMessage(move.error)}</FormAlert>}
          {cancelling ? (
            <ReasonForm
              label={`Why is ${event.name} cancelled?`}
              submit="Cancel event"
              pending={cancel.isPending}
              error={cancel.error}
              onSubmit={(reason) => cancel.mutate(reason)}
              onBack={() => setCancelling(false)}
            />
          ) : (
            <div className="flex flex-wrap gap-2">
              {event.status === "scheduled" && t.status === "in_progress" && (
                <Button aria-label={`Start ${event.name}`} disabled={move.isPending} onClick={() => move.mutate("start")}>
                  Start event
                </Button>
              )}
              {event.status === "in_progress" && (
                <Button aria-label={`Complete ${event.name}`} disabled={move.isPending} onClick={() => move.mutate("complete")}>
                  Complete event
                </Button>
              )}
              <Link to={`/tournaments/${t.id}/events/${event.id}`} aria-label={`Edit ${event.name}`} className={buttonVariants({ variant: "outline" })}>
                <Pencil aria-hidden className="size-4" /> Edit
              </Link>
              {t.status !== "draft" && (
                <Button variant="ghost" aria-label={`Cancel ${event.name}`} className="text-destructive" onClick={() => setCancelling(true)}>
                  Cancel event
                </Button>
              )}
            </div>
          )}
          {event.status === "scheduled" && t.status === "in_progress" && (
            <p className="text-sm text-muted-foreground">Starting fixes the format, best of, seeding, groups and qualifiers.</p>
          )}
        </div>
      )}
    </article>
  )
}

/** A required reason before something is cancelled; it is shown to everyone who can see the tournament. */
function ReasonForm({
  label,
  submit,
  pending,
  error,
  onSubmit,
  onBack,
}: {
  label: string
  submit: string
  pending: boolean
  error: unknown
  onSubmit: (reason: string) => void
  onBack: () => void
}) {
  const [reason, setReason] = useState("")
  const fieldError = error instanceof ApiError ? error.fieldErrors().reason : undefined
  function submitReason(e: FormEvent) {
    e.preventDefault()
    onSubmit(reason.trim())
  }
  return (
    <form onSubmit={submitReason} className="flex flex-col gap-3" noValidate>
      <Field
        label={label}
        required
        maxLength={300}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        error={fieldError}
        hint="Everyone who can see the tournament sees this reason. Cancelling can't be undone."
      />
      {!!error && !fieldError && <FormAlert>{errorMessage(error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" onClick={onBack}>
          Keep it
        </Button>
        <Button type="submit" variant="destructive" disabled={pending}>
          {pending ? "Cancelling…" : submit}
        </Button>
      </div>
    </form>
  )
}

const NEXT: Partial<Record<Tournament["status"], { action: TournamentAction; label: string; note: string }>> = {
  draft: { action: "publish", label: "Publish tournament", note: "Publishing shows the tournament to every player. It needs a venue and at least one event." },
  published: { action: "start", label: "Start tournament", note: "Start on the day. Events are then started one by one." },
  in_progress: { action: "complete", label: "Complete tournament", note: "Every event must be completed or cancelled first." },
}

function Manage({ tournament: t }: { tournament: Tournament }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const onChange = useTournamentChange(t.id)
  const [confirm, setConfirm] = useState<"cancel" | "delete" | null>(null)
  const history = useQuery({ queryKey: tournamentKeys.history(t.id), queryFn: () => getTournamentHistory(t.id) })
  const settled = (fresh: Tournament) => {
    setConfirm(null)
    onChange(fresh)
    void queryClient.invalidateQueries({ queryKey: tournamentKeys.history(t.id) })
  }
  const move = useMutation({ mutationFn: (action: TournamentAction) => moveTournament(t.id, action), onSuccess: settled })
  const cancel = useMutation({ mutationFn: (reason: string) => cancelTournament(t.id, reason), onSuccess: settled })
  const remove = useMutation({
    mutationFn: () => deleteTournament(t.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: tournamentKeys.detail(t.id) })
      await queryClient.invalidateQueries({ queryKey: tournamentKeys.all })
      navigate("/club/tournaments")
    },
  })
  const next = NEXT[t.status]
  const open = !isClosed(t)

  return (
    <section aria-labelledby="manage-heading" className="flex flex-col gap-4 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <div className="flex flex-col gap-1">
        <h2 id="manage-heading" className="text-2xl font-bold">
          Run this tournament
        </h2>
        <p className="text-sm text-muted-foreground">Only people who run competitions for {t.organization.name} see this.</p>
      </div>

      {t.status === "in_progress" && (
        <Link to={`/tournaments/${t.id}/dispatch`} className={buttonVariants({ className: "self-start" })}>
          Tables: send the next matches out
        </Link>
      )}
      {t.status === "in_progress" && (
        <Link to={`/tournaments/${t.id}/scoring`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
          Scoring: matches on the tables and device reports
        </Link>
      )}
      {move.isError && <FormAlert>{errorMessage(move.error)}</FormAlert>}
      {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}

      {confirm === "cancel" && (
        <ReasonForm
          label="Why is the tournament cancelled?"
          submit="Cancel tournament"
          pending={cancel.isPending}
          error={cancel.error}
          onSubmit={(reason) => cancel.mutate(reason)}
          onBack={() => setConfirm(null)}
        />
      )}
      {confirm === "delete" && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1">Delete this draft and its events? This can't be undone.</p>
          <Button variant="outline" onClick={() => setConfirm(null)}>
            Keep it
          </Button>
          <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {remove.isPending ? "Deleting…" : "Delete draft"}
          </Button>
        </div>
      )}
      {confirm === null && open && (
        <div className="flex flex-col gap-2">
          {next && (
            <>
              <Button size="lg" className="self-start" disabled={move.isPending} onClick={() => move.mutate(next.action)}>
                {move.isPending ? "Working…" : next.label}
              </Button>
              <p className="text-sm text-muted-foreground">{next.note}</p>
            </>
          )}
          <div className="flex flex-wrap gap-2">
            <Link to={`/tournaments/${t.id}/edit`} className={buttonVariants({ variant: "outline" })}>
              <Pencil aria-hidden className="size-4" /> Edit details
            </Link>
            {t.status === "draft" ? (
              <Button variant="ghost" className="text-destructive" onClick={() => setConfirm("delete")}>
                Delete draft
              </Button>
            ) : (
              <Button variant="ghost" className="text-destructive" onClick={() => setConfirm("cancel")}>
                Cancel tournament
              </Button>
            )}
          </div>
        </div>
      )}

      {history.isError && <FormAlert>{errorMessage(history.error, "We couldn't load the history.")}</FormAlert>}
      {history.data && history.data.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-lg font-bold">History</h3>
          <ol className="flex flex-col gap-1.5 text-sm">
            {history.data.map((entry) => (
              <li key={entry.id}>
                <span className="font-semibold">
                  {ACTION_LABEL[entry.action]}
                  {entry.event_name && `: ${entry.event_name}`}
                </span>{" "}
                <span className="text-muted-foreground">
                  by {entry.actor_name || "a former member"}, {formatInstant(entry.created_at, t.timezone)}
                </span>
                {entry.reason && <span> — {entry.reason}</span>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  )
}
