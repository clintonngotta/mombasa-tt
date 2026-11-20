import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import {
  askCoach,
  bookSession,
  coachingKeys,
  formatMoney,
  getCoach,
  listCoachings,
  listSlots,
  WEEKDAYS,
  type CoachProfile,
  type Slot,
} from "@/lib/coaching"
import { formatDay, formatInstant } from "@/lib/dates"
import { useMe } from "@/lib/session"
import { LEVEL_LABEL, SKILL_LABEL, type Skill } from "@/lib/training"
import { cn } from "@/lib/utils"

/** A coach's profile (REQ-047): ask them to coach you, or book a session at a free time. */
export function CoachPage() {
  const { id = "" } = useParams()
  const coach = useQuery({ queryKey: coachingKeys.coach(id), queryFn: () => getCoach(id) })
  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <BackLink to="/coaches">Coaches</BackLink>
      {coach.isPending && <p className="text-muted-foreground">Loading…</p>}
      {coach.isError && (
        <FormAlert>{coach.error instanceof ApiError && coach.error.status === 404 ? "This coach isn't taking players." : errorMessage(coach.error)}</FormAlert>
      )}
      {coach.data && <CoachView coach={coach.data} />}
    </div>
  )
}

function CoachView({ coach }: { coach: CoachProfile }) {
  const me = useMe()
  const mine = me.data?.id === coach.user.id
  const timeZone = coach.timezone ?? "Africa/Nairobi"
  const facts = [
    coach.town,
    coach.region,
    formatMoney(coach.rate_minor, coach.currency ?? "KES") && `${formatMoney(coach.rate_minor, coach.currency ?? "KES")} an hour`,
  ].filter(Boolean)

  return (
    <>
      <div className="flex flex-col gap-2">
        <h1 className="text-[32px] leading-9 font-bold">{coach.user.display_name}</h1>
        <p className="text-lg">{coach.headline}</p>
        {facts.length > 0 && <p className="text-muted-foreground">{facts.join(" · ")}</p>}
      </div>
      {coach.bio && <p className="whitespace-pre-line">{coach.bio}</p>}
      <dl className="grid gap-4 sm:grid-cols-2">
        {(coach.levels?.length ?? 0) > 0 && (
          <div>
            <dt className="text-sm text-muted-foreground">Coaches</dt>
            <dd className="font-semibold">{coach.levels!.map((l) => LEVEL_LABEL[l]).join(", ")}</dd>
          </div>
        )}
        {(coach.specialties?.length ?? 0) > 0 && (
          <div>
            <dt className="text-sm text-muted-foreground">Specialities</dt>
            <dd className="font-semibold">{coach.specialties!.map((s) => SKILL_LABEL[s as Skill]).join(", ")}</dd>
          </div>
        )}
        {coach.organizations.length > 0 && (
          <div>
            <dt className="text-sm text-muted-foreground">Coaches at</dt>
            <dd className="font-semibold">{coach.organizations.map((o) => o.name).join(", ")}</dd>
          </div>
        )}
        {coach.availability.length > 0 && (
          <div>
            <dt className="text-sm text-muted-foreground">Usual hours ({timeZone})</dt>
            <dd>
              <ul>
                {coach.availability.map((w, i) => (
                  <li key={i}>
                    {WEEKDAYS[w.weekday]} {w.starts.slice(0, 5)}–{w.ends.slice(0, 5)}
                    {w.venue && ` · ${w.venue}`}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>
      {mine ? (
        <Link to="/coaching/profile" className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
          Edit your profile
        </Link>
      ) : (
        <>
          <AskToCoach coach={coach} />
          <BookSession coach={coach} />
        </>
      )}
    </>
  )
}

function AskToCoach({ coach }: { coach: CoachProfile }) {
  const queryClient = useQueryClient()
  const coachings = useQuery({ queryKey: coachingKeys.coachings, queryFn: listCoachings })
  const [message, setMessage] = useState("")
  const ask = useMutation({
    mutationFn: () => askCoach(coach.user.id, message.trim()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: coachingKeys.coachings }),
  })
  const current = coachings.data?.find((c) => c.coach.id === coach.user.id && c.role === "trainee" && (c.status === "active" || c.status === "requested"))
  if (!coachings.isSuccess) return null

  return (
    <section aria-labelledby="ask-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="ask-heading" className="text-xl font-bold">
        Coaching
      </h2>
      {current?.status === "active" && (
        <p className="flex items-center gap-2 font-semibold text-success">
          <Check aria-hidden className="size-5" /> {coach.user.display_name} coaches you.
        </p>
      )}
      {current?.status === "requested" && (
        <p className="text-muted-foreground">{current.awaiting_me ? "They offered to coach you. Answer on the Coaching tab." : "Request sent. Waiting for them to accept."}</p>
      )}
      {!current && (
        <>
          <p className="text-sm text-muted-foreground">
            Once they accept, your coach sees your matches (your match log and official matches), gives you plans and leaves notes on your
            matches that only you can read. You can stop at any time.
          </p>
          <TextAreaField label="Message" optional rows={2} maxLength={300} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="What would you like to work on?" />
          {ask.isError && <FormAlert>{errorMessage(ask.error)}</FormAlert>}
          <Button className="self-start" disabled={ask.isPending} onClick={() => ask.mutate()}>
            {ask.isPending ? "Sending…" : "Ask to coach me"}
          </Button>
        </>
      )}
    </section>
  )
}

function BookSession({ coach }: { coach: CoachProfile }) {
  const queryClient = useQueryClient()
  const [minutes, setMinutes] = useState<"60" | "90">("60")
  const [chosen, setChosen] = useState<Slot | null>(null)
  const [note, setNote] = useState("")
  const timeZone = coach.timezone ?? "Africa/Nairobi"
  const slots = useQuery({ queryKey: coachingKeys.slots(coach.user.id, Number(minutes)), queryFn: () => listSlots(coach.user.id, Number(minutes)) })
  const book = useMutation({
    mutationFn: (slot: Slot) =>
      bookSession({ coach_id: coach.user.id, starts_at: slot.starts_at, ends_at: slot.ends_at, venue: slot.venue, note: note.trim() }),
    onSuccess: () => {
      setChosen(null)
      setNote("")
      return queryClient.invalidateQueries({ queryKey: coachingKeys.all })
    },
  })
  const byDay = new Map<string, Slot[]>()
  for (const slot of slots.data ?? []) {
    const day = new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(slot.starts_at))
    byDay.set(day, [...(byDay.get(day) ?? []), slot])
  }

  return (
    <section aria-labelledby="book-heading" className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 id="book-heading" className="text-xl font-bold">
        Book a session
      </h2>
      {book.isSuccess && (
        <p role="status" className="font-semibold text-success">
          Requested. {coach.user.display_name} confirms or declines it; you'll see it on the Coaching tab.
        </p>
      )}
      <Segmented
        label="Length"
        options={[
          { value: "60", label: "1 hour" },
          { value: "90", label: "1½ hours" },
        ]}
        value={minutes}
        onChange={(value) => {
          setMinutes(value)
          setChosen(null)
        }}
      />
      {slots.isError && <FormAlert>{errorMessage(slots.error, "We couldn't load free times.")}</FormAlert>}
      {slots.isSuccess && slots.data.length === 0 && <p className="text-muted-foreground">No free times in the next two weeks.</p>}
      <div className="flex flex-col gap-3">
        {[...byDay.entries()].map(([day, daySlots]) => (
          <fieldset key={day} className="flex flex-col gap-2">
            <legend className="mb-1 font-semibold">{formatDay(day)}</legend>
            <div className="flex flex-wrap gap-2">
              {daySlots.map((slot) => (
                <button
                  key={slot.starts_at}
                  type="button"
                  aria-pressed={chosen?.starts_at === slot.starts_at}
                  onClick={() => setChosen(slot)}
                  className={cn(
                    "h-12 rounded-lg border px-3 font-semibold tabular-nums outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    chosen?.starts_at === slot.starts_at ? "border-brand-blue bg-surface-selected text-brand-blue" : "bg-card",
                  )}
                >
                  {formatInstant(slot.starts_at, timeZone).slice(-5)}
                </button>
              ))}
            </div>
          </fieldset>
        ))}
      </div>
      {chosen && (
        <div className="flex flex-col gap-3 border-t pt-4">
          <p className="font-semibold">
            {formatInstant(chosen.starts_at, timeZone)}–{formatInstant(chosen.ends_at, timeZone).slice(-5)}
            {chosen.venue && ` at ${chosen.venue}`}
          </p>
          <TextAreaField label="Note for the coach" optional rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          {book.isError && <FormAlert>{errorMessage(book.error)}</FormAlert>}
          <Button className="self-start" disabled={book.isPending} onClick={() => book.mutate(chosen)}>
            {book.isPending ? "Booking…" : "Request this session"}
          </Button>
        </div>
      )}
    </section>
  )
}
