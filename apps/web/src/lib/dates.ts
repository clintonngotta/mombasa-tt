// Calendar days ("2026-12-05") and instants shown in a named timezone (REQ-007: tournament dates and
// times are the venue's, whatever the viewer's device is set to).

const DAY_MS = 24 * 60 * 60 * 1000

/** A calendar day as a UTC-midnight Date, so formatting with timeZone "UTC" never shifts it. */
const day = (isoDate: string) => new Date(`${isoDate}T00:00:00Z`)

const dayFormat = (options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("en-KE", { timeZone: "UTC", ...options })

/** "5 Dec 2026" or "5 – 6 Dec 2026" or "31 Dec 2026 – 1 Jan 2027". */
export function formatDayRange(startsOn: string, endsOn: string) {
  const full = dayFormat({ day: "numeric", month: "short", year: "numeric" })
  if (startsOn === endsOn) return full.format(day(startsOn))
  const [start, end] = [day(startsOn), day(endsOn)]
  const sameMonth = start.getUTCFullYear() === end.getUTCFullYear() && start.getUTCMonth() === end.getUTCMonth()
  const first = sameMonth
    ? dayFormat({ day: "numeric" }).format(start)
    : dayFormat({ day: "numeric", month: "short", ...(start.getUTCFullYear() === end.getUTCFullYear() ? {} : { year: "numeric" }) }).format(start)
  return `${first} – ${full.format(end)}`
}

/** Today's calendar day in `timeZone`, as "YYYY-MM-DD". */
export function todayIn(timeZone: string, now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(now)
}

/** Whole days from `from` to `to` (both "YYYY-MM-DD"); negative when `to` is earlier. */
export const daysBetween = (from: string, to: string) => Math.round((day(to).getTime() - day(from).getTime()) / DAY_MS)

/** "Sat 5 Dec, 18:00" in the given timezone. */
export function formatInstant(iso: string, timeZone: string) {
  return new Intl.DateTimeFormat("en-KE", {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso))
}

/** The calendar day ("YYYY-MM-DD") an instant falls on in `timeZone`. */
export const dayOf = (iso: string, timeZone: string) => todayIn(timeZone, new Date(iso))

/** "Saturday 5 December" for a calendar day. */
export const formatDay = (isoDate: string) => dayFormat({ weekday: "long", day: "numeric", month: "long" }).format(day(isoDate))

function wallClock(instant: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(instant)
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "00"
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`
}

/** An instant as the value of a datetime-local input showing `timeZone`'s wall clock. */
export const toZonedInput = (iso: string | null, timeZone: string) => (iso ? wallClock(new Date(iso), timeZone) : "")

/** The instant at which `timeZone`'s wall clock reads `local` ("YYYY-MM-DDTHH:mm"); null when blank. */
export function fromZonedInput(local: string, timeZone: string): string | null {
  if (!local) return null
  const asUtc = new Date(`${local}:00Z`).getTime()
  if (Number.isNaN(asUtc)) return null
  // Find the zone's offset at that moment; a second pass settles times next to a clock change.
  let guess = asUtc
  for (let pass = 0; pass < 2; pass++) {
    const shown = new Date(`${wallClock(new Date(guess), timeZone)}:00Z`).getTime()
    guess += asUtc - shown
  }
  return new Date(guess).toISOString()
}

/** Mirrors the API default (core/timezones.py). */
export const DEFAULT_TIME_ZONE = "Africa/Nairobi"

export function timeZones(): string[] {
  const supported = (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf
  return supported ? supported("timeZone") : [DEFAULT_TIME_ZONE]
}
