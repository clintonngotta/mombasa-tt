import { useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, Clock, Globe, LayoutDashboard, ListOrdered, MapPin, Pencil, Plus, Users } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { CeremonyLink } from "@/components/ceremony/CeremonyLink"
import { SponsorsPanel } from "@/components/region/SponsorsPanel"
import { WatchLinks } from "@/components/streams/WatchLinks"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { PlaceDirections } from "@/components/forms/PlaceFinderFields"
import { EventStatusChip, TournamentStatusChip } from "@/components/tournaments/StatusChip"
import { TournamentCover, TournamentDocuments, TournamentMediaManager } from "@/components/tournaments/TournamentMedia"
import { useLiveTournament } from "@/lib/live"
import { ScoreStrip } from "@/components/tournaments/LiveScore"
import { NewsFeed } from "@/components/news/NewsFeed"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships, type Membership } from "@/lib/clubs"
import { formatDayRange, formatInstant } from "@/lib/dates"
import { entryBlock, placesTaken } from "@/lib/entries"
import { countryName } from "@/lib/geography"
import {
  ACTION_LABEL,
  ADMISSION_LABEL,
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
  rejectTournamentApproval,
  SEEDING_LABEL,
  SCOPE_LABEL,
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
  const socketOpen = useLiveTournament(id)
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const t = tournament.data
  const staff = !!t && canManageTournament(memberships, t)
  const missing = tournament.error instanceof ApiError && tournament.error.status === 404

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/tournaments">Tournaments</BackLink>
      {tournament.isPending && <p className="text-muted-foreground">Loading tournament…</p>}
      {missing && <FormAlert>This tournament doesn't exist or hasn't been published.</FormAlert>}
      {tournament.isError && !missing && <FormAlert>{errorMessage(tournament.error, "We couldn't load this tournament.")}</FormAlert>}
      {t && (
        <>
          <Overview tournament={t} />
          {t.status === "in_progress" && <ScoreStrip tournamentId={t.id} socketOpen={socketOpen} />}
          <CeremonyLink tournamentId={t.id} staff={staff} open={t.status !== "draft" && t.status !== "cancelled"} />
          <WatchLinks tournament={t} staff={staff} live={t.status === "in_progress"} />
          <SponsorsPanel tournamentId={t.id} staff={staff} />
          <NewsFeed tournamentId={t.id} staff={staff} timeZone={t.timezone} />
          <Events tournament={t} staff={staff} />
          {staff && <Manage tournament={t} authority={memberships.find((entry) => entry.organization.id === t.organization.id)?.authority} />}
          {!staff && <Approve tournament={t} authority={memberships.find((entry) => entry.organization.id === t.organization.id)?.authority} />}
          {!staff && (t.status === "in_progress" || t.status === "completed") && memberships.some((entry) => entry.organization.id === t.organization.id && entry.authority) && (
            <Link to={`/tournaments/${t.id}/review`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
              The organizers' review
            </Link>
          )}
        </>
      )}
    </div>
  )
}

function Overview({ tournament: t }: { tournament: Tournament }) {
  const soon = countdown(t)
  return (
    <header className="flex flex-col gap-3">
      <TournamentCover cover={t.cover} />
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
          {t.venue && <PlaceDirections place={t.venue} className="mt-1 text-muted-foreground" />}
        </Fact>
        <Fact icon={<Users aria-hidden className="size-5" />} label="Organized by">
          Organized by <span className="font-semibold">{t.organizer.name}</span>
          <span className="text-muted-foreground">
            {" "}
            · {t.organizer.label}
            {t.organizer.kind !== "coach" && t.organizer.kind !== "firm" && t.organization.town && `, ${t.organization.town}`}
          </span>
        </Fact>
        <Fact icon={<Globe aria-hidden className="size-5" />} label="Scope">
          {[
            SCOPE_LABEL[t.scope],
            ...(t.scope === "regional" ? [t.organization.region] : []),
            ...(t.scope === "regional" || t.scope === "national" ? [countryName(t.organization.country)] : []),
          ].filter(Boolean).join(" · ")}
        </Fact>
      </dl>
      <p className="text-sm font-semibold">{formatFee(t.registration_fee)}</p>
      {t.status === "cancelled" && <FormAlert>Cancelled: {t.cancel_reason}</FormAlert>}
      {t.description && <p className="whitespace-pre-line">{t.description}</p>}
      <p className="text-sm text-muted-foreground">Dates and times are venue local ({t.timezone}).</p>
      <TournamentDocuments tournament={t} />
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
        <div className="flex flex-wrap gap-2">
          {t.status !== "draft" && (
            <Link to={`/tournaments/${t.id}/order-of-play`} className={buttonVariants({ variant: "outline" })}>
              <ListOrdered aria-hidden className="size-5" /> Order of play
            </Link>
          )}
          {staff && open && (
            <Link to={`/tournaments/${t.id}/events/new`} className={buttonVariants({ variant: "outline" })}>
              <Plus aria-hidden className="size-5" /> Add event
            </Link>
          )}
        </div>
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
          <p className="text-sm text-muted-foreground">{eventSummary(event)} · {ADMISSION_LABEL[event.admission]}</p>
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
            <Link to={`/tournaments/${t.id}/order-of-play?event=${event.id}`} aria-label={`Order of play for ${event.name}`} className={buttonVariants({ variant: "outline" })}>
              Order of play
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

/** Whether the caller approves this tournament's tier: the platform, the country's official, or the
 * region's official for a regional tournament. The API decides; this only chooses what to show. */
function approves(t: Tournament, authority?: Membership["authority"]) {
  return authority === "platform" || (authority === "country" && t.scope !== "international") || (authority === "regional" && t.scope === "regional")
}

/** For an official who doesn't run the host club: publish a tournament waiting for their approval, or
 * decline it with a reason. */
function Approve({ tournament: t, authority }: { tournament: Tournament; authority?: Membership["authority"] }) {
  const onChange = useTournamentChange(t.id)
  const [declining, setDeclining] = useState(false)
  const publish = useMutation({ mutationFn: () => moveTournament(t.id, "publish"), onSuccess: onChange })
  const reject = useMutation({
    mutationFn: (reason: string) => rejectTournamentApproval(t.id, reason),
    onSuccess: (fresh: Tournament) => {
      setDeclining(false)
      onChange(fresh)
    },
  })
  if (t.status !== "draft" || t.approval_status !== "pending" || !approves(t, authority)) return null
  return (
    <section aria-labelledby="approve-heading" className="flex flex-col gap-3 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <h2 id="approve-heading" className="text-2xl font-bold">
        Waiting for your approval
      </h2>
      <p className="text-sm text-muted-foreground">{t.organizer.name} asked to publish this {SCOPE_LABEL[t.scope].toLowerCase()} tournament.</p>
      {publish.isError && <FormAlert>{errorMessage(publish.error)}</FormAlert>}
      {declining ? (
        <ReasonForm label="Why is approval declined?" submit="Decline approval" pending={reject.isPending} error={reject.error} onSubmit={(reason) => reject.mutate(reason)} onBack={() => setDeclining(false)} />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button disabled={publish.isPending} onClick={() => publish.mutate()}>
            Approve and publish
          </Button>
          <Button variant="outline" onClick={() => setDeclining(true)}>
            Decline approval
          </Button>
        </div>
      )}
    </section>
  )
}

const NEXT: Partial<Record<Tournament["status"], { action: TournamentAction; label: string; note: string }>> = {
  draft: { action: "publish", label: "Publish tournament", note: "Publishing shows the tournament to every player. It needs a venue and at least one event." },
  published: { action: "start", label: "Start tournament", note: "Start on the day. Events are then started one by one." },
  in_progress: { action: "complete", label: "Complete tournament", note: "Every event must be completed or cancelled first." },
}

function Manage({ tournament: t, authority }: { tournament: Tournament; authority?: Membership["authority"] }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const onChange = useTournamentChange(t.id)
  const [confirm, setConfirm] = useState<"cancel" | "delete" | "reject" | null>(null)
  const history = useQuery({ queryKey: tournamentKeys.history(t.id), queryFn: () => getTournamentHistory(t.id) })
  const settled = (fresh: Tournament) => {
    setConfirm(null)
    onChange(fresh)
    void queryClient.invalidateQueries({ queryKey: tournamentKeys.history(t.id) })
  }
  const move = useMutation({ mutationFn: (action: TournamentAction) => moveTournament(t.id, action), onSuccess: settled })
  const cancel = useMutation({ mutationFn: (reason: string) => cancelTournament(t.id, reason), onSuccess: settled })
  const reject = useMutation({ mutationFn: (reason: string) => rejectTournamentApproval(t.id, reason), onSuccess: settled })
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
  const needsApproval = t.status === "draft" && t.scope !== "local"
  const canApprove = approves(t, authority)
  const pendingApproval = t.approval_status === "pending"

  return (
    <section aria-labelledby="manage-heading" className="flex flex-col gap-4 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <div className="flex flex-col gap-1">
        <h2 id="manage-heading" className="text-2xl font-bold">
          Run this tournament
        </h2>
        <p className="text-sm text-muted-foreground">Only people who run competitions for {t.organizer.name} see this.</p>
      </div>

      <Link to={`/tournaments/${t.id}/dashboard`} className={buttonVariants({ className: "self-start" })}>
        <LayoutDashboard aria-hidden className="size-4" /> Dashboard: entries, draws and matches
      </Link>

      {open && <TournamentMediaManager tournament={t} />}

      {(t.status === "published" || t.status === "in_progress") && (
        <Link to={`/tournaments/${t.id}/schedule-plan`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
          Schedule: plan times and tables
        </Link>
      )}
      {(t.status === "published" || t.status === "in_progress") && (
        <Link to={`/tournaments/${t.id}/order-of-play`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
          Order of play: stage order, release time and late starts
        </Link>
      )}
      {t.status === "in_progress" && (
        <Link to={`/tournaments/${t.id}/dispatch`} className={buttonVariants({ className: "self-start" })}>
          Control centre: tables, calls and check-in
        </Link>
      )}
      {(t.status === "in_progress" || t.status === "completed") && (
        <Link to={`/tournaments/${t.id}/review`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
          Review: what went well, what went wrong, actions
        </Link>
      )}
      {t.events.some((event) => event.paused_at) && (
        <Link to={`/tournaments/${t.id}/corrections`} className={buttonVariants({ variant: "destructive", className: "self-start" })}>
          An event is paused: decide about a corrected result
        </Link>
      )}
      {t.status === "in_progress" && !t.events.some((event) => event.paused_at) && (
        <Link to={`/tournaments/${t.id}/corrections`} className={buttonVariants({ variant: "outline", className: "self-start" })}>
          Corrections
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
      {confirm === "reject" && (
        <ReasonForm label="Why is approval declined?" submit="Decline approval" pending={reject.isPending}
          error={reject.error} onSubmit={(reason) => reject.mutate(reason)} onBack={() => setConfirm(null)} />
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
          {next && !needsApproval && (
            <>
              <Button size="lg" className="self-start" disabled={move.isPending} onClick={() => move.mutate(next.action)}>
                {move.isPending ? "Working…" : next.label}
              </Button>
              <p className="text-sm text-muted-foreground">{next.note}</p>
            </>
          )}
          {needsApproval && (
            <>
              {pendingApproval && <p className="text-sm font-semibold">Waiting for official approval</p>}
              {!pendingApproval && (
                <Button className="self-start" disabled={move.isPending} onClick={() => move.mutate("approval/request")}>
                  {t.approval_status === "rejected" ? "Request approval again" : "Request approval"}
                </Button>
              )}
              {pendingApproval && canApprove && <div className="flex flex-wrap gap-2">
                <Button disabled={move.isPending} onClick={() => move.mutate("publish")}>Approve and publish</Button>
                <Button variant="outline" onClick={() => setConfirm("reject")}>Decline approval</Button>
              </div>}
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
