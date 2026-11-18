import { useState, type FormEvent } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, Crown } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { PlayerPicker, type Picked } from "@/components/tournaments/PlayerPicker"
import { EntryStatusChip, EventStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { formatInstant, todayIn } from "@/lib/dates"
import {
  changeEntry,
  createEntry,
  entryBlock,
  entryKeys,
  entryTitle,
  isLive,
  listEntries,
  listMyEntries,
  MAX_TEAM_ROSTER,
  POOL_LABEL,
  placesTaken,
  selfCheckIn,
  withdrawEntry,
  type Entry,
  type EntryStatus,
  type StaffEntryAction,
} from "@/lib/entries"
import { useMe } from "@/lib/session"
import { canManageTournament, eventSummary, formatFee, getTournament, isClosed, tournamentKeys, type Tournament, type TournamentEvent } from "@/lib/tournaments"

/** Entries of one event (REQ-008): enter or withdraw, see who is in, and the organizers' entry desk. */
export function EntriesPage() {
  const { id = "", eventId = "" } = useParams()
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const entries = useQuery({ queryKey: entryKeys.event(eventId), queryFn: () => listEntries(id, eventId), enabled: tournament.isSuccess })
  const t = tournament.data
  const event = t?.events.find((candidate) => candidate.id === eventId)
  const staff = !!t && canManageTournament(memberships, t)
  const missing = (tournament.error instanceof ApiError && tournament.error.status === 404) || (!!t && !event)
  // The caller's own entries come from their own list, so they are found however many the event has.
  const own = useQuery({ queryKey: entryKeys.mine, queryFn: listMyEntries, enabled: tournament.isSuccess })
  const all = entries.data?.results ?? []
  const mine = (own.data?.results ?? []).filter((entry) => entry.event.id === eventId)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      {tournament.isPending && <p className="text-muted-foreground">Loading event…</p>}
      {missing && <FormAlert>This event doesn't exist or hasn't been published.</FormAlert>}
      {tournament.isError && !missing && <FormAlert>{errorMessage(tournament.error, "We couldn't load this event.")}</FormAlert>}
      {t && event && (
        <>
          <header className="flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <h1 className="min-w-0 text-[32px] leading-9 font-bold break-words">{event.name}: entries</h1>
              <EventStatusChip status={event.status} />
            </div>
            <p className="text-muted-foreground">{eventSummary(event)}</p>
            <p className="font-semibold">{placesTaken(event)}</p>
            {event.entry_fee.amount_minor > 0 && (
              <p className="text-sm text-muted-foreground">
                Entry fee: {formatFee(event.entry_fee)}, paid the way the organizers ask. Payments aren't recorded here yet, so “Accepted” means a place in the
                event and says nothing about the fee.
              </p>
            )}
          </header>
          {entries.isPending && <p className="text-muted-foreground">Loading entries…</p>}
          {entries.isError && <FormAlert>{errorMessage(entries.error, "We couldn't load the entries.")}</FormAlert>}
          {entries.isSuccess && (
            <>
              {entries.data.count > all.length && (
                <FormAlert>
                  Showing the first {all.length} of {entries.data.count} entries.
                </FormAlert>
              )}
              <MyEntry tournament={t} event={event} staff={staff} entries={mine} />
              {staff ? <Desk tournament={t} event={event} entries={all} /> : <Accepted entries={all.filter((entry) => entry.status === "accepted")} />}
            </>
          )}
        </>
      )}
    </div>
  )
}

/** After any change: this event's entries, the places taken on the tournament, and "my entries". */
function useEntryChange(t: Tournament, event: TournamentEvent) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: entryKeys.event(event.id) })
    void queryClient.invalidateQueries({ queryKey: entryKeys.mine })
    void queryClient.invalidateQueries({ queryKey: tournamentKeys.detail(t.id) })
  }
}

function Players({ entry }: { entry: Entry }) {
  if (!entry.team_name) return null
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground">
      {entry.players.map((player) => (
        <li key={player.id} className="flex items-center gap-1">
          {player.id === entry.captain_id && <Crown aria-label="Captain" className="size-4" />}
          {player.display_name}
        </li>
      ))}
    </ul>
  )
}

function CheckedIn({ entry, zone }: { entry: Entry; zone: string }) {
  if (!entry.checked_in_at) return null
  return (
    <p className="flex items-center gap-1 text-sm font-semibold text-success">
      <CircleCheck aria-hidden className="size-4" /> Checked in {formatInstant(entry.checked_in_at, zone)}
    </p>
  )
}

function MyEntry({ tournament: t, event, staff, entries }: { tournament: Tournament; event: TournamentEvent; staff: boolean; entries: Entry[] }) {
  const onChange = useEntryChange(t, event)
  const [confirming, setConfirming] = useState(false)
  const live = entries.find(isLive)
  const last = entries[0] // newest first
  const block = entryBlock(t, event, { staff })
  const today = todayIn(t.timezone)
  const checkInDay = t.starts_on <= today && today <= t.ends_on
  const checkIn = useMutation({
    mutationFn: (entryId: string) => selfCheckIn(t.id, event.id, entryId),
    onSuccess: onChange,
  })
  const withdraw = useMutation({
    mutationFn: (entryId: string) => withdrawEntry(t.id, event.id, entryId),
    onSuccess: () => {
      setConfirming(false)
      onChange()
    },
  })

  return (
    <section aria-labelledby="my-entry-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="my-entry-heading" className="text-2xl font-bold">
        Your entry
      </h2>
      {live ? (
        <>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="min-w-0 text-lg font-semibold break-words">{entryTitle(live)}</p>
            <EntryStatusChip status={live.status} />
          </div>
          <Players entry={live} />
          <CheckedIn entry={live} zone={t.timezone} />
          {live.status === "accepted" && !live.checked_in_at && live.my_check_in_at && (
            <p className="text-sm text-success">You’re checked in. Waiting for the rest of your entry.</p>
          )}
          {live.status === "accepted" && !live.my_check_in_at && !live.checked_in_at && checkInDay && !isClosed(event) && !isClosed(t) && (
            <Button type="button" className="self-start" disabled={checkIn.isPending} onClick={() => checkIn.mutate(live.id)}>
              {checkIn.isPending ? "Checking in…" : "Check in now"}
            </Button>
          )}
          {checkIn.isError && <FormAlert>{errorMessage(checkIn.error)}</FormAlert>}
          {live.status === "pending" && <p className="text-sm text-muted-foreground">The organizers accept entries one by one. You'll get an email when they decide.</p>}
          {live.status === "waitlisted" && <p className="text-sm text-muted-foreground">The event is full for now. The organizers will email you if a place opens up.</p>}
          {withdraw.isError && <FormAlert>{errorMessage(withdraw.error)}</FormAlert>}
          {event.status === "scheduled" && !isClosed(t) ? (
            confirming ? (
              <div className="flex flex-wrap items-center gap-2">
                <p className="flex-1">Withdraw this entry? {live.status === "accepted" && "You give up your place."}</p>
                <Button variant="outline" onClick={() => setConfirming(false)}>
                  Stay in
                </Button>
                <Button variant="destructive" disabled={withdraw.isPending} onClick={() => withdraw.mutate(live.id)}>
                  {withdraw.isPending ? "Withdrawing…" : "Withdraw entry"}
                </Button>
              </div>
            ) : (
              <Button variant="outline" className="self-start" onClick={() => setConfirming(true)}>
                Withdraw
              </Button>
            )
          ) : (
            <p className="text-sm text-muted-foreground">The event has started, so entries are fixed. If you can't play, tell the tournament desk before your match.</p>
          )}
        </>
      ) : (
        <>
          {last && (
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span>Your last entry:</span>
                <EntryStatusChip status={last.status} />
              </div>
              {last.reason && <p className="text-sm">Reason given: {last.reason}</p>}
            </div>
          )}
          {block ? <p className="text-muted-foreground">{block}</p> : <EnterForm tournament={t} event={event} mode={staff ? "own-as-staff" : "own"} onDone={onChange} />}
        </>
      )}
    </section>
  )
}

const ROSTER_SIZE: Record<TournamentEvent["kind"], number> = { singles: 1, doubles: 2, team: MAX_TEAM_ROSTER, jumbles: 1 }
type Pool = keyof typeof POOL_LABEL
const POOLS: { value: Pool; label: string; description: string }[] = [
  { value: "men", label: POOL_LABEL.men, description: "Partnered with a woman each round" },
  { value: "women", label: POOL_LABEL.women, description: "Partnered with a man each round" },
]
const DIRECTORY_HINT = "Only players listed in the player directory can be found. Anyone can list themselves from their profile."

/** Enter the event: yourself (with a partner or a team), or anybody when the organizers do it. */
function EnterForm({ tournament: t, event, mode, onDone }: { tournament: Tournament; event: TournamentEvent; mode: "own" | "own-as-staff" | "desk"; onDone: () => void }) {
  const staff = mode === "desk"
  const me = useMe().data
  const [picked, setPicked] = useState<Picked[]>([])
  const [teamName, setTeamName] = useState("")
  const [captain, setCaptain] = useState("")
  const [pool, setPool] = useState<Pool | "">("")
  const fixed = !staff && me ? [{ id: me.id, display_name: me.display_name }] : []
  const players = [...fixed, ...picked]
  const captainId = players.some((player) => player.id === captain) ? captain : (players[0]?.id ?? "")
  const enter = useMutation({
    mutationFn: () =>
      createEntry(t.id, event.id, {
        player_ids: players.map((player) => player.id),
        ...(event.kind === "team" ? { team_name: teamName.trim(), captain_id: captainId || null } : {}),
        ...(event.kind === "jumbles" && pool ? { pool } : {}),
      }),
    onSuccess: () => {
      setPicked([])
      setTeamName("")
      setPool("")
      onDone()
    },
  })
  const fieldErrors = enter.error instanceof ApiError ? enter.error.fieldErrors() : {}
  const other = enter.isError && Object.keys(fieldErrors).length === 0
  const needsPicker = staff || (event.kind !== "singles" && event.kind !== "jumbles")

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    enter.mutate()
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {event.kind === "team" && (
        <Field label="Team name" required maxLength={80} value={teamName} onChange={(e) => setTeamName(e.target.value)} error={fieldErrors.team_name} />
      )}
      {event.kind === "jumbles" && (
        <ChoiceGroup legend="Pool" options={POOLS} value={pool} onChange={setPool} error={fieldErrors.pool} />
      )}
      {needsPicker ? (
        <PlayerPicker
          label={event.kind === "singles" || event.kind === "jumbles" ? "Player" : event.kind === "doubles" ? (staff ? "The two players" : "Your partner") : "Players"}
          hint={DIRECTORY_HINT}
          picked={picked}
          fixed={fixed}
          max={ROSTER_SIZE[event.kind]}
          error={fieldErrors.player_ids}
          onChange={setPicked}
        />
      ) : (
        fieldErrors.player_ids && <FormAlert>{fieldErrors.player_ids}</FormAlert>
      )}
      {event.kind === "team" && players.length > 0 && (
        <SelectField
          label="Captain"
          value={captainId}
          onChange={setCaptain}
          error={fieldErrors.captain_id}
          options={players.map((player) => ({ value: player.id, label: player.display_name }))}
        />
      )}
      {other && <FormAlert>{errorMessage(enter.error)}</FormAlert>}
      <Button type="submit" size="lg" className="self-start" disabled={enter.isPending}>
        {enter.isPending ? "Entering…" : staff ? "Add entry" : `Enter ${event.name}`}
      </Button>
      {mode === "own" && (
        <p className="text-sm text-muted-foreground">
          {event.admission === "open"
            ? "Your entry is accepted automatically if there is a place. If the event is full, you join the waiting list."
            : "The organizers review your request and decide whether to accept it."}
        </p>
      )}
      {mode === "own-as-staff" && (
        <p className="text-sm text-muted-foreground">You run this tournament, so your own entry takes a place straight away, or joins the waiting list if the event is full.</p>
      )}
    </form>
  )
}

function Accepted({ entries }: { entries: Entry[] }) {
  return (
    <section aria-labelledby="accepted-heading" className="flex flex-col gap-3">
      <h2 id="accepted-heading" className="text-2xl font-bold">
        Accepted entries
      </h2>
      {entries.length === 0 ? (
        <p className="text-muted-foreground">Nobody has been accepted yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {entries.map((entry) => (
            <li key={entry.id} className="flex flex-col gap-1 rounded-lg border bg-card p-3">
              <p className="font-semibold break-words">{entryTitle(entry)}</p>
              {entry.pool && <p className="text-sm text-muted-foreground">{POOL_LABEL[entry.pool]}</p>}
              <Players entry={entry} />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

const GROUPS: { status: EntryStatus; title: string; empty: string }[] = [
  { status: "pending", title: "Waiting for a decision", empty: "No entries are waiting." },
  { status: "accepted", title: "Accepted", empty: "Nobody has been accepted yet." },
  { status: "waitlisted", title: "Waiting list", empty: "The waiting list is empty." },
  { status: "rejected", title: "Not accepted", empty: "" },
  { status: "withdrawn", title: "Withdrawn", empty: "" },
]

/** The organizers' entry desk: decide, check in, withdraw, and enter people themselves. */
function Desk({ tournament: t, event, entries }: { tournament: Tournament; event: TournamentEvent; entries: Entry[] }) {
  const onChange = useEntryChange(t, event)
  const [adding, setAdding] = useState(false)
  const taking = t.status !== "draft" && !isClosed(t) && event.status === "scheduled"
  const checkingIn = t.status !== "draft" && !isClosed(t) && !isClosed(event)

  return (
    <section aria-labelledby="desk-heading" className="flex flex-col gap-4 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <div className="flex flex-col gap-1">
        <h2 id="desk-heading" className="text-2xl font-bold">
          Entry desk
        </h2>
        <p className="text-sm text-muted-foreground">Only people who run competitions for {t.organization.name} see this.</p>
      </div>
      {!taking && <p className="text-muted-foreground">{t.status === "draft" ? "Entries open once the tournament is published." : "Entries can't change now; check-in stays open until the event ends."}</p>}

      {taking &&
        (adding ? (
          <div className="flex flex-col gap-3 rounded-lg border bg-card p-3">
            <h3 className="text-lg font-bold">Add an entry</h3>
            <p className="text-sm text-muted-foreground">It takes a place straight away, or joins the waiting list if the event is full. The players get an email.</p>
            <EnterForm tournament={t} event={event} mode="desk" onDone={onChange} />
            <Button variant="ghost" className="self-start" onClick={() => setAdding(false)}>
              Done adding
            </Button>
          </div>
        ) : (
          <Button variant="outline" className="self-start" onClick={() => setAdding(true)}>
            Add an entry
          </Button>
        ))}

      {GROUPS.map((group) => {
        const rows = entries.filter((entry) => entry.status === group.status)
        if (rows.length === 0 && !group.empty) return null
        return (
          <div key={group.status} className="flex flex-col gap-2">
            <h3 className="text-lg font-bold">
              {group.title} ({rows.length})
            </h3>
            {rows.length === 0 && <p className="text-sm text-muted-foreground">{group.empty}</p>}
            {rows.length > 0 && (
              <ul className="flex flex-col gap-2">
                {rows.map((entry) => (
                  <li key={entry.id}>
                    <DeskRow tournament={t} event={event} entry={entry} taking={taking} checkingIn={checkingIn} onChange={onChange} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        )
      })}
    </section>
  )
}

function DeskRow({
  tournament: t,
  event,
  entry,
  taking,
  checkingIn,
  onChange,
}: {
  tournament: Tournament
  event: TournamentEvent
  entry: Entry
  taking: boolean
  checkingIn: boolean
  onChange: () => void
}) {
  const [asking, setAsking] = useState<"reject" | "staff-withdraw" | null>(null)
  const [reason, setReason] = useState("")
  const change = useMutation({
    mutationFn: (action: StaffEntryAction) => changeEntry(t.id, event.id, entry.id, action, asking ? reason.trim() : undefined),
    onSuccess: () => {
      setAsking(null)
      setReason("")
      onChange()
    },
  })
  const title = entryTitle(entry)
  const act = (action: StaffEntryAction, label: string, variant: "default" | "outline" = "outline") => (
    <Button variant={variant} aria-label={`${label}: ${title}`} disabled={change.isPending} onClick={() => change.mutate(action)}>
      {label}
    </Button>
  )

  return (
    <article aria-label={title} className="flex flex-col gap-2 rounded-lg border bg-card p-3">
      <p className="font-semibold break-words">{title}</p>
      <Players entry={entry} />
      <CheckedIn entry={entry} zone={t.timezone} />
      {entry.reason && <p className="text-sm">Reason given: {entry.reason}</p>}
      {change.isError && <FormAlert>{errorMessage(change.error)}</FormAlert>}
      {asking ? (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            change.mutate(asking)
          }}
        >
          <Field label="Reason" optional maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="The entry's players see this reason." />
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => setAsking(null)}>
              Back
            </Button>
            <Button type="submit" variant="destructive" disabled={change.isPending}>
              {asking === "reject" ? "Reject entry" : "Withdraw entry"}
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          {taking && entry.status === "pending" && (
            <>
              {act("accept", "Accept", "default")}
              {act("waitlist", "Waiting list")}
            </>
          )}
          {taking && entry.status === "waitlisted" && act("accept", "Give a place", "default")}
          {checkingIn && entry.status === "accepted" && (entry.checked_in_at ? act("undo-check-in", "Undo check-in") : act("check-in", "Check in", "default"))}
          {taking && (entry.status === "pending" || entry.status === "waitlisted") && (
            <Button variant="ghost" className="text-destructive" aria-label={`Reject: ${title}`} onClick={() => setAsking("reject")}>
              Reject
            </Button>
          )}
          {taking && entry.status === "accepted" && (
            <Button variant="ghost" className="text-destructive" aria-label={`Withdraw: ${title}`} onClick={() => setAsking("staff-withdraw")}>
              Withdraw
            </Button>
          )}
        </div>
      )}
    </article>
  )
}
