import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, Dumbbell } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { ConflictList } from "@/components/training/ConflictList"
import { errorMessage } from "@/lib/api"
import { branchSchedule, clashesOf, joinOpenSession, leaveOpenSession, LEVEL_LABEL, listOpenSessions, openSessionKeys, type OpenSession } from "@/lib/clubSessions"
import { formatMoney } from "@/lib/coaching"
import { formatInstant } from "@/lib/dates"
import { ROW } from "@/lib/clubAdmin"
import { trainingKeys } from "@/lib/training"

const KIND = { training: "Training", activity: "Event", tournament: "Tournament" } as const

/** A branch's training slots any player may join, joining and leaving them (REQ-044, REQ-027). */
export function BranchTraining({ venueId, timeZone }: { venueId: string; timeZone: string }) {
  const sessions = useQuery({ queryKey: openSessionKeys.venue(venueId), queryFn: () => listOpenSessions(venueId) })
  const list = sessions.data?.results ?? []
  if (sessions.isSuccess && list.length === 0) return null
  return (
    <section aria-labelledby="training-heading" className="flex flex-col gap-2">
      <h2 id="training-heading" className="flex items-center gap-2 text-xl font-bold">
        <Dumbbell aria-hidden className="size-5 text-brand-blue" /> Training you can join
      </h2>
      {sessions.isError && <FormAlert>{errorMessage(sessions.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {list.map((session) => (
          <li key={session.id}>
            <Slot session={session} timeZone={timeZone} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function Slot({ session, timeZone }: { session: OpenSession; timeZone: string }) {
  const queryClient = useQueryClient()
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: openSessionKeys.all })
    void queryClient.invalidateQueries({ queryKey: trainingKeys.all })
  }
  const join = useMutation({ mutationFn: () => joinOpenSession(session.id), onSuccess: done })
  const leave = useMutation({ mutationFn: () => leaveOpenSession(session.id), onSuccess: done })
  const clashes = clashesOf(join.error)
  const full = session.places_left === 0 && !session.joined
  return (
    <div className={`${ROW} flex-col items-stretch`}>
      <div className="flex flex-col gap-0.5">
        <p className="font-semibold">{session.title}</p>
        <p>
          {formatInstant(session.starts_at, timeZone)} to {formatInstant(session.ends_at, timeZone).slice(-5)}
        </p>
        <p className="text-sm text-muted-foreground">
          {[session.level ? LEVEL_LABEL[session.level] : "", session.coach_name ? `with ${session.coach_name}` : "", session.fee_minor != null ? `${formatMoney(session.fee_minor, session.fee_currency ?? "KES")} at the door` : "", session.places_left != null ? `${session.places_left} places left` : ""]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {session.notes && <p className="text-sm whitespace-pre-wrap">{session.notes}</p>}
      </div>
      <ConflictList conflicts={clashes} timeZone={timeZone} lead="You already have something on then:" next="Move it, or choose another session." />
      {(join.isError || leave.isError) && !clashes.length && <FormAlert>{errorMessage(join.error ?? leave.error)}</FormAlert>}
      <div className="flex gap-2">
        {session.joined ? (
          <Button variant="outline" disabled={leave.isPending} onClick={() => leave.mutate()}>
            Leave
          </Button>
        ) : (
          <Button disabled={join.isPending || full} onClick={() => join.mutate()}>
            {full ? "Full" : "Join"}
          </Button>
        )}
        {session.joined && <span className="self-center text-sm font-semibold text-success">You're in</span>}
      </div>
    </div>
  )
}

/** Everything the branch has coming up, in date order. */
export function BranchSchedule({ venueId, timeZone }: { venueId: string; timeZone: string }) {
  const items = useQuery({ queryKey: openSessionKeys.branchSchedule(venueId), queryFn: () => branchSchedule(venueId) })
  if (!items.data?.length) return null
  return (
    <section aria-labelledby="branch-schedule-heading" className="flex flex-col gap-2">
      <h2 id="branch-schedule-heading" className="flex items-center gap-2 text-xl font-bold">
        <CalendarDays aria-hidden className="size-5 text-brand-blue" /> Coming up
      </h2>
      <ul className="flex flex-col gap-1">
        {items.data.map((item) => (
          <li key={`${item.kind}-${item.id}`} className="flex flex-wrap gap-x-2">
            <span className="tabular-nums text-muted-foreground">{formatInstant(item.starts_at, timeZone)}</span>
            <span className="font-semibold">{item.title}</span>
            <span className="text-sm text-muted-foreground">{KIND[item.kind]}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
