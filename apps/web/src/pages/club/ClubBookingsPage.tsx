import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ConflictList } from "@/components/training/ConflictList"
import { errorMessage } from "@/lib/api"
import { approveBooking, bookingKeys, cancelClubBooking, listClubBookings, rejectBooking, STATUS_LABEL, type TableBooking } from "@/lib/bookings"
import { clashesOf } from "@/lib/clubSessions"
import { can, useActiveMembership } from "@/lib/clubs"
import { useAdminAccessLost } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { DEFAULT_TIME_ZONE, formatInstant } from "@/lib/dates"
import { cn } from "@/lib/utils"

const TABS = [
  { value: "requested", label: "Requested" },
  { value: "approved", label: "Approved" },
  { value: "", label: "All" },
]

/** Booking requests at the organization's venues (REQ-021): requested and approved shown apart. */
export function ClubBookingsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const timeZone = active?.organization.timezone ?? DEFAULT_TIME_ZONE
  const allowed = can(active, "facilities.manage")
  const [tab, setTab] = useState("requested")
  const bookings = useQuery({ queryKey: bookingKeys.club(orgId, tab), queryFn: () => listClubBookings(orgId, tab), enabled: allowed })
  const accessLost = useAdminAccessLost(bookings.error)
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">Table bookings</h1>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          <div role="group" aria-label="Which bookings" className="flex self-start rounded-lg border bg-card p-1">
            {TABS.map((t) => (
              <button key={t.value} type="button" aria-pressed={tab === t.value} onClick={() => setTab(t.value)} className={cn("h-12 rounded-md px-4 font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50", tab === t.value && "bg-surface-selected text-brand-blue")}>
                {t.label}
              </button>
            ))}
          </div>
          {bookings.isError && <FormAlert>{errorMessage(bookings.error)}</FormAlert>}
          {bookings.isSuccess && bookings.data.results.length === 0 && <p className="text-muted-foreground">None.</p>}
          <ul className="flex flex-col gap-2">
            {(bookings.data?.results ?? []).map((b) => (
              <li key={b.id}>
                <Request orgId={orgId} booking={b} timeZone={timeZone} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function Request({ orgId, booking: b, timeZone }: { orgId: string; booking: TableBooking; timeZone: string }) {
  const queryClient = useQueryClient()
  const [fee, setFee] = useState("")
  const [reason, setReason] = useState("")
  const run = useMutation({ mutationFn: (step: () => Promise<TableBooking>) => step(), onSuccess: () => queryClient.invalidateQueries({ queryKey: bookingKeys.all }) })
  const clashes = clashesOf(run.error)
  return (
    <article className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">
        {b.requester_name} · {b.venue_name}, {b.tables.join(", ")}
      </p>
      <p className="text-sm text-muted-foreground">
        {formatInstant(b.starts_at, timeZone)} to {formatInstant(b.ends_at, timeZone).slice(-5)} · {STATUS_LABEL[b.status]}
        {b.fee_minor != null && ` · ${formatMoney(b.fee_minor, b.fee_currency)}`}
        {b.ended && " · ended"}
      </p>
      {b.note && <p className="text-sm">"{b.note}"</p>}
      <ConflictList conflicts={clashes} timeZone={timeZone} lead="A table is taken then:" next="Decline it, or ask the player for another time." />
      {run.isError && !clashes.length && <FormAlert>{errorMessage(run.error)}</FormAlert>}
      {b.status === "requested" && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Fee (KES)" optional type="number" min={0} className="w-36" value={fee} onChange={(e) => setFee(e.target.value)} />
          <Button disabled={run.isPending} onClick={() => run.mutate(() => approveBooking(orgId, b.id, fee ? Math.round(Number(fee) * 100) : null))}>
            Approve
          </Button>
        </div>
      )}
      {(b.status === "requested" || (b.status === "approved" && !b.ended)) && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Reason" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          {b.status === "requested" ? (
            <Button variant="outline" disabled={!reason.trim() || run.isPending} onClick={() => run.mutate(() => rejectBooking(orgId, b.id, reason.trim()))}>
              Decline
            </Button>
          ) : (
            <Button variant="outline" className="text-destructive" disabled={run.isPending} onClick={() => run.mutate(() => cancelClubBooking(orgId, b.id, reason.trim()))}>
              Cancel booking
            </Button>
          )}
        </div>
      )}
    </article>
  )
}
