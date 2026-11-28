import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarClock, ChevronRight, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ConflictList } from "@/components/training/ConflictList"
import { ApiError, errorMessage } from "@/lib/api"
import { can, listMembers, useActiveMembership } from "@/lib/clubs"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { clashesOf, clubSessionKeys, createClubSession, listClubSessions, type ClubSession, type ClubSessionInput, type When } from "@/lib/clubSessions"
import { DEFAULT_TIME_ZONE, formatInstant, fromZonedInput } from "@/lib/dates"
import { listVenues, runsFacility, venueKeys } from "@/lib/venues"
import { cn } from "@/lib/utils"
import { OrganizationName } from "@/components/clubs/KindBadge"

/**
 * Club training sessions (REQ-027) for the club's training staff: schedule a session on the club's tables,
 * invite members, and take attendance. Saving takes the tables; a member's time is held only when they
 * accept.
 */
export function ClubSessionsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const timeZone = active?.organization.timezone ?? DEFAULT_TIME_ZONE
  const allowed = can(active, "training.manage")
  const [when, setWhen] = useState<When>("upcoming")
  const [adding, setAdding] = useState(false)
  const sessions = useQuery({ queryKey: clubSessionKeys.list(orgId, when), queryFn: () => listClubSessions(orgId, when), enabled: allowed })
  const accessLost = useAdminAccessLost(sessions.error)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Training sessions</h1>
        {active && <p className="text-muted-foreground"><OrganizationName organization={active.organization} /></p>}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          {adding ? (
            <NewSession orgId={orgId} timeZone={timeZone} facility={runsFacility(active?.organization.kind)} onClose={() => setAdding(false)} />
          ) : (
            <Button className="self-start" onClick={() => setAdding(true)}>
              <Plus aria-hidden className="size-5" /> Schedule a session
            </Button>
          )}
          <div role="group" aria-label="Which sessions" className="flex self-start rounded-lg border bg-card p-1">
            {(["upcoming", "past"] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={when === value}
                onClick={() => setWhen(value)}
                className={cn("h-12 rounded-md px-4 font-semibold text-muted-foreground capitalize outline-none focus-visible:ring-3 focus-visible:ring-ring/50", when === value && "bg-surface-selected text-brand-blue")}
              >
                {value}
              </button>
            ))}
          </div>
          {sessions.isError && <FormAlert>{errorMessage(sessions.error, "We couldn't load the sessions.")}</FormAlert>}
          {sessions.isSuccess && sessions.data.results.length === 0 && <p className="text-muted-foreground">{when === "upcoming" ? "No sessions scheduled." : "No past sessions."}</p>}
          <ul className="flex flex-col gap-2">
            {(sessions.data?.results ?? []).map((session) => (
              <li key={session.id}>
                <SessionRow session={session} timeZone={timeZone} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function SessionRow({ session, timeZone }: { session: ClubSession; timeZone: string }) {
  const cancelled = session.status === "cancelled"
  return (
    <Link to={`/club/sessions/${session.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
      <CalendarClock aria-hidden className="size-5 text-brand-blue" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={cn("truncate font-semibold", cancelled && "line-through")}>{session.title}</span>
        <span className="text-sm text-muted-foreground">
          {formatInstant(session.starts_at, timeZone)} · {session.tables.map((t) => t.label).join(", ")}
        </span>
        <span className="text-sm text-muted-foreground">
          {cancelled ? "Cancelled" : `${session.accepted} coming of ${session.invited} invited${session.capacity ? ` · ${session.capacity} places` : ""}`}
        </span>
      </span>
      <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
    </Link>
  )
}

const LEVELS = [
  { value: "", label: "Any level" },
  { value: "beginner", label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced", label: "Advanced" },
]

function NewSession({ orgId, timeZone, facility, onClose }: { orgId: string; timeZone: string; facility: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId) })
  const draft = useDraft(`club-session-new:${orgId}`)
  const [title, setTitle] = useDraftState(draft, "title", "")
  const [starts, setStarts] = useDraftState(draft, "starts", "")
  const [ends, setEnds] = useDraftState(draft, "ends", "")
  const [tables, setTables] = useDraftState<string[]>(draft, "tables", [])
  const [capacity, setCapacity] = useDraftState(draft, "capacity", "")
  const [notes, setNotes] = useDraftState(draft, "notes", "")
  const [coach, setCoach] = useDraftState(draft, "coach", "")
  const [level, setLevel] = useDraftState(draft, "level", "")
  const [fee, setFee] = useDraftState(draft, "fee", "")
  const [open, setOpen] = useDraftState(draft, "open", facility)
  const [weeks, setWeeks] = useDraftState(draft, "weeks", "1")
  const members = useQuery({ queryKey: ["clubs", orgId, "members", ""], queryFn: () => listMembers(orgId, "") })
  // A facility keeps its match tables for play; training goes on its training tables.
  const options = (venues.data ?? [])
    .filter((venue) => venue.active)
    .flatMap((venue) =>
      venue.tables.filter((table) => table.active && (!facility || table.kind === "training")).map((table) => ({ value: table.id, label: table.label, description: venue.name }))
    )
  const save = useMutation({
    mutationFn: () =>
      createClubSession(orgId, {
        title: title.trim(),
        notes: notes.trim(),
        table_ids: tables,
        starts_at: fromZonedInput(starts, timeZone) ?? "",
        ends_at: fromZonedInput(ends, timeZone) ?? "",
        capacity: capacity ? Number(capacity) : null,
        coach_id: coach || null,
        level: (level || "") as ClubSessionInput["level"],
        fee_minor: fee ? Math.round(Number(fee) * 100) : null,
        fee_currency: "KES",
        open_to_players: open,
        repeat_weeks: Number(weeks) || 1,
      }),
    onSuccess: (made) => {
      draft.clear()
      void queryClient.invalidateQueries({ queryKey: clubSessionKeys.all })
      navigate(`/club/sessions/${made.id}`)
    },
  })
  const error = save.error instanceof ApiError ? save.error : null
  const errors = error?.fieldErrors() ?? {}
  const clashes = clashesOf(save.error)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">Schedule a session</h2>
      <Field label="Title" required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Tuesday squad" error={errors.title} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Starts" type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} error={errors.starts_at} hint={`Times are in ${timeZone}.`} />
        <Field label="Ends" type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} error={errors.ends_at} />
      </div>
      {venues.isSuccess && options.length === 0 ? (
        <p className="text-muted-foreground">
          Add the club's tables first, under <Link to="/club/venues" className="font-semibold text-brand-blue underline-offset-4 hover:underline">Venues and tables</Link>.
        </p>
      ) : (
        <ChoiceGroup legend="Tables" multiple options={options} value={tables} onChange={setTables} error={errors.table_ids} />
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField label="Coach" value={coach} onChange={setCoach} options={[{ value: "", label: "No coach named" }, ...(members.data?.results ?? []).map((m) => ({ value: m.user, label: m.display_name }))]} error={errors.coach_id} />
        <SelectField label="Level" value={level} onChange={setLevel} options={LEVELS} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Fee at the door (KES)" optional type="number" min={0} step="0.01" inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} hint="Shown to players. Collected at the door, not here." error={errors.fee_minor} />
        <Field label="Repeat weekly" type="number" min={1} max={12} inputMode="numeric" value={weeks} onChange={(e) => setWeeks(e.target.value)} hint="How many weeks in a row, up to 12." error={errors.repeat_weeks} />
      </div>
      <label className="flex min-h-12 items-center gap-3">
        <input type="checkbox" className="size-5 accent-brand-blue" checked={open} onChange={(e) => setOpen(e.target.checked)} />
        <span>
          <span className="font-semibold">Any player can join</span> <span className="text-muted-foreground">: listed on your public profile, not only for those you invite.</span>
        </span>
      </label>
      <Field label="Places" optional type="number" min={1} max={500} inputMode="numeric" value={capacity} onChange={(e) => setCapacity(e.target.value)} hint="Most members who can accept. Leave empty for no limit." error={errors.capacity} />
      <TextAreaField label="Notes for members" optional maxLength={1000} rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      <ConflictList conflicts={clashes} timeZone={timeZone} lead="A table you chose is in use then:" next="Choose other tables or another time." />
      {save.isError && !clashes.length && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <DraftBar draft={draft} />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={save.isPending || !title.trim() || !starts || !ends || !tables.length}>
          {save.isPending ? "Saving…" : "Save session"}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
