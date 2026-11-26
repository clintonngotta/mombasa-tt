import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, ChevronRight, GraduationCap, Search, UserRound } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import {
  answerBooking,
  answerCoaching,
  BOOKING_STATUS_LABEL,
  coachingKeys,
  getMyCoachProfileOrNull,
  listBookings,
  listCoachings,
  type Booking,
  type Coaching,
} from "@/lib/coaching"
import { formatInstant } from "@/lib/dates"
import { LOCAL_TIME_ZONE } from "@/lib/training"
import { cn } from "@/lib/utils"
import { CoachCalendar } from "@/components/coaching/CoachCalendar"
import { OrganizeTournament } from "@/components/coaching/OrganizeTournament"
import { TraineeTaskBoard } from "@/components/coaching/TraineeTaskBoard"

/** Coaching (REQ-047): requests waiting for you, the people you coach and your week as a coach, and the
 * coaches you train with and the sessions you booked. */
export function CoachingTab() {
  const profile = useQuery({
    queryKey: coachingKeys.profile,
    queryFn: getMyCoachProfileOrNull,
  })
  const coachings = useQuery({ queryKey: coachingKeys.coachings, queryFn: listCoachings })
  const bookings = useQuery({ queryKey: coachingKeys.bookings, queryFn: listBookings })
  const all = coachings.data ?? []
  const waiting = all.filter((c) => c.awaiting_me)
  const trainees = all.filter((c) => c.role === "coach" && c.status === "active")
  const coaches = all.filter((c) => c.role === "trainee" && (c.status === "active" || (c.status === "requested" && !c.awaiting_me)))
  const asCoach = (bookings.data ?? []).filter((b) => b.role === "coach")
  const asTrainee = (bookings.data ?? []).filter((b) => b.role === "trainee" && (b.status === "requested" || b.status === "confirmed"))

  return (
    <>
      {(coachings.isError || bookings.isError || profile.isError) && (
        <FormAlert>{errorMessage(coachings.error ?? bookings.error ?? profile.error, "We couldn't load your coaching.")}</FormAlert>
      )}
      {waiting.length > 0 && <Requests coachings={waiting} />}

      {profile.data && (
        <>
          <Trainees coachings={trainees} />
          <SessionRequests bookings={asCoach.filter((b) => b.status === "requested")} />
          <TraineeTaskBoard coachings={trainees} />
          <CoachCalendar profile={profile.data} />
        </>
      )}
      {profile.isSuccess && (
        <section aria-labelledby="coach-heading" className={cn(ROW, "justify-between")}>
          <span className="flex min-w-0 flex-col">
            <span id="coach-heading" className="font-semibold">
              {profile.data ? "Your coach profile" : "Coach other players"}
            </span>
            <span className="text-sm text-muted-foreground">
              {profile.data
                ? profile.data.accepting
                  ? "Players can find you and book sessions in your available hours."
                  : "You're not taking new players. Your trainees can still book."
                : "Set up a profile and weekly hours. Players ask you to coach them and book sessions."}
            </span>
          </span>
          <Link to="/coaching/profile" className={buttonVariants({ variant: profile.data ? "outline" : "default" })}>
            {profile.data ? "Edit profile and hours" : "Become a coach"}
          </Link>
        </section>
      )}
      {profile.data && <OrganizeTournament profile={profile.data} />}

      <section aria-labelledby="my-coaches-heading" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="my-coaches-heading" className="text-xl font-bold">
            My coaches
          </h2>
          <Link to="/coaches" className={buttonVariants({ variant: "outline" })}>
            <Search aria-hidden className="size-4" /> Find a coach
          </Link>
        </div>
        {coachings.isSuccess && coaches.length === 0 && <p className="text-muted-foreground">You don't train with a coach yet.</p>}
        <ul className="flex flex-col gap-2">
          {coaches.map((c) => (
            <li key={c.id}>
              <Link to={`/coaches/${c.coach.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                <UserRound aria-hidden className="size-5 text-brand-blue" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-semibold">{c.coach.display_name}</span>
                  <span className="text-sm text-muted-foreground">{c.status === "active" ? "Coaching you" : "Waiting for them to accept"}</span>
                </span>
                <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ul>
        <MySessions bookings={asTrainee} />
      </section>
    </>
  )
}

function useRefresh() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: coachingKeys.all })
}

function Requests({ coachings }: { coachings: Coaching[] }) {
  const refresh = useRefresh()
  const answer = useMutation({ mutationFn: ({ id, action }: { id: string; action: "accept" | "decline" }) => answerCoaching(id, action), onSuccess: refresh })
  return (
    <section aria-labelledby="requests-heading" className="flex flex-col gap-3">
      <h2 id="requests-heading" className="text-xl font-bold">
        Waiting for your answer
      </h2>
      {answer.isError && <FormAlert>{errorMessage(answer.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {coachings.map((c) => (
          <li key={c.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">
                {c.role === "coach" ? `${c.trainee.display_name} asks you to coach them` : `${c.coach.display_name} offers to coach you`}
              </span>
              {c.message && <span className="text-sm text-muted-foreground">“{c.message}”</span>}
              {c.role === "trainee" && <span className="text-sm text-muted-foreground">If you accept, they see your matches and can give you plans.</span>}
            </span>
            <Button disabled={answer.isPending} onClick={() => answer.mutate({ id: c.id, action: "accept" })}>
              Accept
            </Button>
            <Button variant="outline" disabled={answer.isPending} onClick={() => answer.mutate({ id: c.id, action: "decline" })}>
              Decline
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Trainees({ coachings }: { coachings: Coaching[] }) {
  return (
    <section aria-labelledby="trainees-heading" className="flex flex-col gap-3">
      <h2 id="trainees-heading" className="text-xl font-bold">
        Trainees
      </h2>
      {coachings.length === 0 ? (
        <p className="text-muted-foreground">Nobody yet. Players who ask you to coach them appear here once you accept.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {coachings.map((c) => (
            <li key={c.id}>
              <Link to={`/coaching/trainees/${c.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                <GraduationCap aria-hidden className="size-5 text-brand-blue" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-semibold">{c.trainee.display_name}</span>
                  <span className="text-sm text-muted-foreground">Progress, plans, matches and notes</span>
                </span>
                <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function SessionRequests({ bookings }: { bookings: Booking[] }) {
  const refresh = useRefresh()
  const answer = useMutation({ mutationFn: ({ id, action }: { id: string; action: "confirm" | "decline" }) => answerBooking(id, action), onSuccess: refresh })
  if (bookings.length === 0) return null
  return (
    <section aria-labelledby="session-requests-heading" className="flex flex-col gap-3">
      <h2 id="session-requests-heading" className="text-xl font-bold">
        Session requests
      </h2>
      {answer.isError && <FormAlert>{errorMessage(answer.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {bookings.map((b) => (
          <li key={b.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">{b.trainee.display_name}</span>
              <span className="text-sm text-muted-foreground">
                {formatInstant(b.starts_at, LOCAL_TIME_ZONE)}–{formatInstant(b.ends_at, LOCAL_TIME_ZONE).slice(-5)}
                {b.venue && ` · ${b.venue}`}
              </span>
              {b.note && <span className="text-sm">“{b.note}”</span>}
            </span>
            <Button disabled={answer.isPending} onClick={() => answer.mutate({ id: b.id, action: "confirm" })}>
              Confirm
            </Button>
            <Button variant="outline" disabled={answer.isPending} onClick={() => answer.mutate({ id: b.id, action: "decline" })}>
              Decline
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function MySessions({ bookings }: { bookings: Booking[] }) {
  const refresh = useRefresh()
  const cancel = useMutation({ mutationFn: (id: string) => answerBooking(id, "cancel"), onSuccess: refresh })
  if (bookings.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-semibold">Sessions you booked</h3>
      {cancel.isError && <FormAlert>{errorMessage(cancel.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {bookings.map((b) => (
          <li key={b.id} className={ROW}>
            <CalendarDays aria-hidden className="size-5 text-brand-blue" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">With {b.coach.display_name}</span>
              <span className="text-sm text-muted-foreground">
                {formatInstant(b.starts_at, LOCAL_TIME_ZONE)} · {BOOKING_STATUS_LABEL[b.status]}
                {b.venue && ` · ${b.venue}`}
              </span>
            </span>
            <Button variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate(b.id)}>
              Cancel
            </Button>
          </li>
        ))}
      </ul>
    </div>
  )
}
