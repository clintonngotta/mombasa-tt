import { DraftBar } from "@/components/forms/Draft"
import { useDraft, useDraftState } from "@/components/forms/useDraft"
import { useState, type FormEvent } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { LocationFields } from "@/components/forms/LocationFields"
import { TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { WEEKDAYS } from "@/lib/coaching"
import { hhmm } from "@/lib/facilities"
import { PROFILE_OPTIONS, saveVenueHours, updateVenue, venueKeys, type Closure, type OpeningHour, type Venue, type VenueProfile } from "@/lib/venues"

function useSaved(orgId: string) {
  const queryClient = useQueryClient()
  return (saved: Venue) => {
    queryClient.setQueryData<Venue[]>(venueKeys.list(orgId), (old) => old?.map((v) => (v.id === saved.id ? saved : v)))
    void queryClient.invalidateQueries({ queryKey: ["facilities"] })
  }
}

/** The branch profile players see in the facility finder (REQ-044): where it is, contact, rules,
 * what a visitor gets, and who may find it. */
export function BranchProfile({ orgId, venue }: { orgId: string; venue: Venue }) {
  const saved = useSaved(orgId)
  const draft = useDraft(`branch-profile:${venue.id}`)
  const [location, setLocation] = useDraftState(draft, "location", { country: venue.country, region: venue.region, city: venue.town })
  const [phone, setPhone] = useDraftState(draft, "phone", venue.phone)
  const [rules, setRules] = useDraftState(draft, "rules", venue.rules)
  const [amenities, setAmenities] = useDraftState(draft, "amenities", venue.amenities.join("\n"))
  const [profile, setProfile] = useDraftState<VenueProfile>(draft, "profile", venue.profile)
  const save = useMutation({
    mutationFn: () =>
      updateVenue(orgId, venue.id, {
        country: location.country,
        region: location.region,
        town: location.city,
        phone: phone.trim(),
        rules: rules.trim(),
        amenities: amenities
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
        profile,
      }),
    onSuccess: (fresh) => {
      draft.clear()
      saved(fresh)
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <section aria-labelledby="branch-heading" className="flex flex-col gap-4 border-t pt-6">
      <h2 id="branch-heading" className="text-2xl font-bold">
        Branch profile
      </h2>
      <p className="text-sm text-muted-foreground">What players see when they look for a place to play.</p>
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <LocationFields value={location} onChange={setLocation} errors={{ ...errors, city: errors.town ?? errors.city }} cityLimit={80} />
        <Field label="Phone" optional type="tel" maxLength={30} value={phone} onChange={(e) => setPhone(e.target.value)} error={errors.phone} />
        <TextAreaField label="Rules" optional maxLength={2000} rows={3} value={rules} onChange={(e) => setRules(e.target.value)} error={errors.rules} />
        <TextAreaField
          label="What visitors get"
          optional
          rows={4}
          value={amenities}
          onChange={(e) => setAmenities(e.target.value)}
          hint="One per line, for example Ball hire, Changing rooms, Coaching corner."
          error={errors.amenities}
        />
        <ChoiceGroup legend="Who finds this branch" options={PROFILE_OPTIONS} value={profile} onChange={setProfile} columns={3} error={errors.profile} />
        {save.isError && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
        <DraftBar draft={draft} />
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save profile"}
          </Button>
          {save.isSuccess && (
            <span role="status" className="text-sm text-success">
              Saved.
            </span>
          )}
        </div>
      </form>
    </section>
  )
}

type Block = { key: string; weekday: number; opens: string; closes: string }
type Shut = { key: string; starts_on: string; ends_on: string; reason: string }
let counter = 0
const key = () => `row-${++counter}`

/** Weekly opening hours and closures, in the organization's timezone, saved together. */
export function OpeningHours({ orgId, venue, timeZone }: { orgId: string; venue: Venue; timeZone: string }) {
  const saved = useSaved(orgId)
  const [blocks, setBlocks] = useState<Block[]>(() => venue.opening_hours.map((h) => ({ key: key(), weekday: h.weekday, opens: hhmm(h.opens), closes: hhmm(h.closes) })))
  const [closures, setClosures] = useState<Shut[]>(() => venue.closures.map((c) => ({ key: key(), starts_on: c.starts_on, ends_on: c.ends_on, reason: c.reason ?? "" })))
  const save = useMutation({
    mutationFn: () =>
      saveVenueHours(
        orgId,
        venue.id,
        blocks.map(({ weekday, opens, closes }): OpeningHour => ({ weekday, opens, closes })),
        closures.map(({ starts_on, ends_on, reason }): Closure => ({ starts_on, ends_on, reason: reason.trim() }))
      ),
    onSuccess: saved,
  })
  const setBlock = (k: string, patch: Partial<Block>) => setBlocks(blocks.map((b) => (b.key === k ? { ...b, ...patch } : b)))
  const setClosure = (k: string, patch: Partial<Shut>) => setClosures(closures.map((c) => (c.key === k ? { ...c, ...patch } : c)))
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  return (
    <section aria-labelledby="hours-heading" className="flex flex-col gap-4 border-t pt-6">
      <h2 id="hours-heading" className="text-2xl font-bold">
        Opening hours
      </h2>
      <p className="text-sm text-muted-foreground">In {timeZone}. A day without hours is closed. Add a second block for a break in the day.</p>
      <ul className="flex flex-col gap-4">
        {WEEKDAYS.map((day, weekday) => {
          const today = blocks.filter((b) => b.weekday === weekday)
          return (
            <li key={day} className="flex flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{day}</span>
                <Button type="button" variant="ghost" size="sm" onClick={() => setBlocks([...blocks, { key: key(), weekday, opens: "08:00", closes: "20:00" }])}>
                  <Plus aria-hidden className="size-4" /> Add hours
                </Button>
              </div>
              {today.length === 0 && <span className="text-sm text-muted-foreground">Closed</span>}
              {today.map((block) => (
                <div key={block.key} className="flex flex-wrap items-end gap-2">
                  <Field label={`${day} opens`} type="time" className="w-36" value={block.opens} onChange={(e) => setBlock(block.key, { opens: e.target.value })} />
                  <Field label="Closes" type="time" className="w-36" value={block.closes} onChange={(e) => setBlock(block.key, { closes: e.target.value })} />
                  <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${day} ${block.opens} to ${block.closes}`} onClick={() => setBlocks(blocks.filter((b) => b.key !== block.key))}>
                    <Trash2 aria-hidden className="size-5" />
                  </Button>
                </div>
              ))}
            </li>
          )
        })}
      </ul>
      <h3 className="text-xl font-bold">Closures</h3>
      <p className="text-sm text-muted-foreground">Holidays and other days the branch stays shut, whatever the weekly hours say.</p>
      {closures.map((closure) => (
        <div key={closure.key} className="flex flex-wrap items-end gap-2 rounded-xl border bg-card p-3">
          <Field label="From" type="date" className="w-44" value={closure.starts_on} onChange={(e) => setClosure(closure.key, { starts_on: e.target.value, ends_on: closure.ends_on || e.target.value })} />
          <Field label="To" type="date" className="w-44" value={closure.ends_on} onChange={(e) => setClosure(closure.key, { ends_on: e.target.value })} />
          <Field label="Why" optional maxLength={120} className="min-w-40 flex-1" value={closure.reason} onChange={(e) => setClosure(closure.key, { reason: e.target.value })} placeholder="Public holiday" />
          <Button type="button" variant="ghost" size="icon" aria-label="Remove this closure" onClick={() => setClosures(closures.filter((c) => c.key !== closure.key))}>
            <Trash2 aria-hidden className="size-5" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" className="self-start" onClick={() => setClosures([...closures, { key: key(), starts_on: "", ends_on: "", reason: "" }])}>
        <Plus aria-hidden className="size-4" /> Add a closure
      </Button>
      {save.isError && <FormAlert>{Object.keys(errors).length ? "Check the hours: closing comes after opening, blocks on one day don't overlap, and a closure ends on or after its first day." : errorMessage(save.error)}</FormAlert>}
      <div className="flex items-center gap-3">
        <Button disabled={save.isPending || closures.some((c) => !c.starts_on || !c.ends_on)} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save hours"}
        </Button>
        {save.isSuccess && (
          <span role="status" className="text-sm text-success">
            Saved.
          </span>
        )}
      </div>
    </section>
  )
}
