import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { bookingKeys, cancelMyBooking, listMyBookings, STATUS_LABEL } from "@/lib/bookings"
import { ROW } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { formatInstant } from "@/lib/dates"
import { LOCAL_TIME_ZONE } from "@/lib/training"

/** The player's table booking requests and their answers (REQ-021). */
export function MyBookingsPage() {
  const queryClient = useQueryClient()
  const bookings = useQuery({ queryKey: bookingKeys.mine, queryFn: listMyBookings })
  const cancel = useMutation({ mutationFn: (id: string) => cancelMyBooking(id), onSuccess: () => queryClient.invalidateQueries({ queryKey: bookingKeys.all }) })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/profile">Profile</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Table bookings</h1>
      {bookings.isError && <FormAlert>{errorMessage(bookings.error)}</FormAlert>}
      {cancel.isError && <FormAlert>{errorMessage(cancel.error)}</FormAlert>}
      {bookings.isSuccess && bookings.data.results.length === 0 && <p className="text-muted-foreground">No bookings. Find a facility to book a table.</p>}
      <ul className="flex flex-col gap-2">
        {(bookings.data?.results ?? []).map((b) => (
          <li key={b.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">
                {b.venue_name} · {b.tables.join(", ")}
              </span>
              <span className="text-sm text-muted-foreground">
                {formatInstant(b.starts_at, LOCAL_TIME_ZONE)} · {STATUS_LABEL[b.status]}
                {b.fee_minor != null && ` · ${formatMoney(b.fee_minor, b.fee_currency)} at the venue`}
                {b.reason && ` · ${b.reason}`}
              </span>
            </span>
            {(b.status === "requested" || b.status === "approved") && !b.ended && (
              <Button variant="ghost" disabled={cancel.isPending} onClick={() => cancel.mutate(b.id)}>
                Cancel
              </Button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
