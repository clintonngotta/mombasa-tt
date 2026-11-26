import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CalendarX, Check, Clock, MapPin, Phone, ScrollText, Ticket } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { PlaceDirections } from "@/components/forms/PlaceFinderFields"
import { OpenBadge } from "@/components/facilities/OpenBadge"
import { OrganizationGallery } from "@/components/clubs/OrganizationGallery"
import { useMe } from "@/lib/session"
import { BookTable } from "@/components/facilities/BookTable"
import { BranchSchedule, BranchTraining } from "@/components/facilities/BranchTraining"
import { errorMessage } from "@/lib/api"
import { WEEKDAYS } from "@/lib/coaching"
import { formatMoney } from "@/lib/coaching"
import { formatDayRange } from "@/lib/dates"
import { facilityKeys, getFacility, hhmm } from "@/lib/facilities"

/** One facility branch as players see it (REQ-044): open now, hours, closures, rules, what a visit
 * includes and how to get there. */
export function FacilityPage() {
  const { id = "" } = useParams()
  const facility = useQuery({ queryKey: facilityKeys.detail(id), queryFn: () => getFacility(id) })
  const f = facility.data
  const signedIn = useMe().isSuccess

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/facilities">Find a place to play</BackLink>
      {facility.isError && <FormAlert>{errorMessage(facility.error, "This facility isn't available.")}</FormAlert>}
      {f && (
        <>
          <header className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-[32px] leading-9 font-bold">{f.name}</h1>
              <OpenBadge open={f.open_now} />
            </div>
            <p className="text-lg text-muted-foreground">{f.organization_name}</p>
            <p className="flex items-center gap-1.5">
              <MapPin aria-hidden className="size-4 text-brand-blue" /> {[f.address, f.town, f.region].filter(Boolean).join(", ")}
            </p>
            {f.phone && (
              <a href={`tel:${f.phone.replace(/[^+0-9]/g, "")}`} className="flex items-center gap-1.5 self-start font-semibold text-brand-blue underline-offset-4 hover:underline">
                <Phone aria-hidden className="size-4" /> {f.phone}
              </a>
            )}
            <PlaceDirections place={f} />
            <p className="text-sm text-muted-foreground">
              {f.match_tables} match {f.match_tables === 1 ? "table" : "tables"}
              {f.training_tables > 0 && ` · ${f.training_tables} training ${f.training_tables === 1 ? "table" : "tables"}`}
            </p>
          </header>

          {/* The facility's pictures are for signed-in players, as its organization's profile is. */}
          {signedIn && <OrganizationGallery orgId={f.organization_id} />}

          {f.closed_today && (
            <p role="status" className="flex items-center gap-2 rounded-xl border border-warning/40 bg-warning/10 p-4 font-semibold">
              <CalendarX aria-hidden className="size-5 text-warning" /> Closed today{f.closed_today.reason ? `: ${f.closed_today.reason}` : ""}
            </p>
          )}

          <section aria-labelledby="hours-heading" className="flex flex-col gap-2">
            <h2 id="hours-heading" className="flex items-center gap-2 text-xl font-bold">
              <Clock aria-hidden className="size-5 text-brand-blue" /> Opening hours
            </h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
              {WEEKDAYS.map((day, weekday) => {
                const blocks = f.opening_hours.filter((h) => h.weekday === weekday)
                return (
                  <div key={day} className="contents">
                    <dt className="font-semibold">{day}</dt>
                    <dd className="tabular-nums">{blocks.length ? blocks.map((h) => `${hhmm(h.opens)}–${hhmm(h.closes)}`).join(", ") : "Closed"}</dd>
                  </div>
                )
              })}
            </dl>
            <p className="text-sm text-muted-foreground">Times in {f.timezone}.</p>
            {f.closures.length > 0 && (
              <>
                <h3 className="mt-2 font-semibold">Closed on</h3>
                <ul className="flex flex-col gap-1">
                  {f.closures.map((c) => (
                    <li key={`${c.starts_on}-${c.ends_on}`}>
                      {formatDayRange(c.starts_on, c.ends_on)}
                      {c.reason ? `: ${c.reason}` : ""}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <BookTable venueId={f.id} timeZone={f.timezone} tables={f.bookable_tables} />
          <BranchSchedule venueId={f.id} timeZone={f.timezone} />
          <BranchTraining venueId={f.id} timeZone={f.timezone} />

          {f.passes.length > 0 && (
            <section aria-labelledby="prices-heading" className="flex flex-col gap-2">
              <h2 id="prices-heading" className="flex items-center gap-2 text-xl font-bold">
                <Ticket aria-hidden className="size-5 text-brand-blue" /> Prices
              </h2>
              <ul className="flex flex-col gap-2">
                {f.passes.map((pass) => (
                  <li key={pass.id} className="flex flex-col rounded-xl border bg-card p-4">
                    <span className="flex flex-wrap justify-between gap-2 font-semibold">
                      <span>{pass.name}</span>
                      <span className="tabular-nums">{formatMoney(pass.amount_minor, pass.currency ?? "KES")}</span>
                    </span>
                    {pass.kind === "sessions" && (
                      <span className="text-sm text-muted-foreground">
                        {pass.sessions} visits within {pass.valid_days} days
                      </span>
                    )}
                    {pass.benefits && pass.benefits.length > 0 && <span className="text-sm">{pass.benefits.join(" · ")}</span>}
                  </li>
                ))}
              </ul>
              <p className="text-sm text-muted-foreground">Pay at the door. Coast TT doesn't take payments.</p>
            </section>
          )}

          {f.amenities.length > 0 && (
            <section aria-labelledby="amenities-heading" className="flex flex-col gap-2">
              <h2 id="amenities-heading" className="text-xl font-bold">
                What a visit includes
              </h2>
              <ul className="flex flex-col gap-1">
                {f.amenities.map((amenity) => (
                  <li key={amenity} className="flex items-center gap-2">
                    <Check aria-hidden className="size-4 text-success" /> {amenity}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {f.rules && (
            <section aria-labelledby="rules-heading" className="flex flex-col gap-2">
              <h2 id="rules-heading" className="flex items-center gap-2 text-xl font-bold">
                <ScrollText aria-hidden className="size-5 text-brand-blue" /> Rules
              </h2>
              <p className="whitespace-pre-wrap">{f.rules}</p>
            </section>
          )}
        </>
      )}
    </div>
  )
}
