import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { answerBooking, coachingKeys, type Booking } from "@/lib/coaching"

/** Whether the coach can mark this session done: it is confirmed and has started. */
export const canMarkDone = (booking: Booking, now: number) => booking.role === "coach" && booking.status === "confirmed" && new Date(booking.starts_at).getTime() <= now

/** The coach's "Mark as done" for a session that was held (REQ-047). */
export function MarkDoneButton({ booking }: { booking: Booking }) {
  const queryClient = useQueryClient()
  const done = useMutation({
    mutationFn: () => answerBooking(booking.id, "complete"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: coachingKeys.all }),
  })
  return (
    <span className="flex flex-col items-end gap-1">
      <Button variant="outline" disabled={done.isPending} onClick={() => done.mutate()}>
        <Check aria-hidden className="size-4" /> {done.isPending ? "Saving…" : "Mark as done"}
      </Button>
      {done.isError && (
        <span role="alert" className="text-sm text-destructive">
          We couldn't save that. Try again.
        </span>
      )}
    </span>
  )
}
