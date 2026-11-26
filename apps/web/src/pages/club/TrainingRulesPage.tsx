import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Clock, MapPin, Plus, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { useActiveMembership } from "@/lib/clubs"
import { getTrainingRules, MAX_CHECK_IN_RADIUS, rulesKey, saveTrainingRules, WEEKDAYS, WEEKDAY_LABEL, type TrainingRules, type TrainingSlot, type Weekday } from "@/lib/clubSessions"
import { locate } from "@/lib/nearby"
import { listVenues, venueKeys } from "@/lib/venues"

/** How the club trains (REQ-052): its weekly slots, where it usually trains, and when and from how far a
 * member may check in. Members read it; training staff change it. */
export function TrainingRulesPage() {
  const { active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const rules = useQuery({ queryKey: rulesKey(orgId), queryFn: () => getTrainingRules(orgId), enabled: !!orgId, staleTime: 0 })
  const [editing, setEditing] = useState(false)
  const r = rules.data
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">{active?.organization.name ?? "Club"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Training rules</h1>
        <p className="text-muted-foreground">When the club trains, where, and how checking in works.</p>
      </div>
      {rules.isError && <FormAlert>{errorMessage(rules.error, "Training rules are for the club's members.")}</FormAlert>}
      {r && !editing && (
        <>
          <RulesText rules={r} />
          {r.can_edit && (
            <Button className="self-start" onClick={() => setEditing(true)}>
              Change the rules
            </Button>
          )}
        </>
      )}
      {r && editing && <RulesForm key={r.updated_at} orgId={orgId} rules={r} onDone={() => setEditing(false)} />}
    </div>
  )
}

function RulesText({ rules }: { rules: TrainingRules }) {
  const place = rules.venue?.name ?? rules.location_label
  return (
    <>
      <section aria-labelledby="slots-heading" className="flex flex-col gap-2">
        <h2 id="slots-heading" className="flex items-center gap-2 text-xl font-bold">
          <Clock aria-hidden className="size-5 text-brand-blue" /> Weekly schedule
        </h2>
        {rules.slots.length === 0 ? (
          <p className="text-muted-foreground">No weekly slots set yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {rules.slots.map((slot, i) => (
              <li key={i} className="rounded-lg border bg-card px-3 py-2">
                <span className="font-semibold">{WEEKDAY_LABEL[slot.weekday]}</span> {slot.starts} to {slot.ends}
                {slot.title && <span className="text-muted-foreground"> · {slot.title}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="place-heading" className="flex flex-col gap-2">
        <h2 id="place-heading" className="flex items-center gap-2 text-xl font-bold">
          <MapPin aria-hidden className="size-5 text-brand-blue" /> Where we train
        </h2>
        <p>{place || "Not set yet."}</p>
        {!rules.has_location && <p className="text-sm text-muted-foreground">Until the place has a position on the map, the coach marks attendance by hand.</p>}
      </section>
      <section aria-labelledby="check-in-heading" className="flex flex-col gap-2">
        <h2 id="check-in-heading" className="text-xl font-bold">
          Checking in
        </h2>
        <ul className="list-disc pl-6">
          <li>
            Check-in opens {rules.opens_before_minutes} minutes before a session starts and closes {rules.closes_after_minutes} minutes after.
          </li>
          <li>Later than {rules.late_after_minutes} minutes after the start counts as late.</li>
          <li>You check in on your phone, within {rules.radius_m} m of where the session is held.</li>
          <li>Your location is used for that check only. The club sees how far away you were, not where.</li>
          <li>No phone, or no signal? The coach can mark you present.</li>
        </ul>
      </section>
    </>
  )
}

type Place = "none" | "venue" | "point"

function RulesForm({ orgId, rules, onDone }: { orgId: string; rules: TrainingRules; onDone: () => void }) {
  const queryClient = useQueryClient()
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId) })
  const [slots, setSlots] = useState<TrainingSlot[]>(() => rules.slots.map((slot) => ({ ...slot })))
  const [place, setPlace] = useState<Place>(rules.venue ? "venue" : rules.latitude ? "point" : "none")
  const [venue, setVenue] = useState(rules.venue?.id ?? "")
  const [point, setPoint] = useState<{ latitude: number; longitude: number } | null>(rules.latitude && rules.longitude ? { latitude: Number(rules.latitude), longitude: Number(rules.longitude) } : null)
  const [label, setLabel] = useState(rules.location_label)
  const [radius, setRadius] = useState(String(rules.radius_m))
  const [before, setBefore] = useState(String(rules.opens_before_minutes))
  const [after, setAfter] = useState(String(rules.closes_after_minutes))
  const [late, setLate] = useState(String(rules.late_after_minutes))
  const here = useMutation({ mutationFn: () => locate({ fresh: true }), onSuccess: (found) => setPoint({ latitude: Number(found.latitude.toFixed(6)), longitude: Number(found.longitude.toFixed(6)) }) })
  const save = useMutation({
    mutationFn: () =>
      saveTrainingRules(orgId, {
        slots: slots.filter((slot) => slot.starts && slot.ends),
        venue_id: place === "venue" && venue ? venue : null,
        latitude: place === "point" && point ? String(point.latitude) : null,
        longitude: place === "point" && point ? String(point.longitude) : null,
        location_label: place === "point" ? label.trim() : "",
        radius_m: Number(radius),
        opens_before_minutes: Number(before),
        closes_after_minutes: Number(after),
        late_after_minutes: Number(late),
      }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(rulesKey(orgId), fresh)
      onDone()
    },
  })
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const setSlot = (index: number, change: Partial<TrainingSlot>) => setSlots(slots.map((slot, i) => (i === index ? { ...slot, ...change } : slot)))

  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-5 rounded-xl border bg-card p-4"
    >
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-semibold">Weekly schedule</legend>
        {slots.map((slot, i) => (
          <div key={i} className="grid items-end gap-2 sm:grid-cols-[10rem_7rem_7rem_1fr_auto]">
            <SelectField label="Day" options={WEEKDAYS.map((day) => ({ value: day, label: WEEKDAY_LABEL[day] }))} value={slot.weekday} onChange={(day) => setSlot(i, { weekday: day as Weekday })} />
            <Field label="From" type="time" value={slot.starts} onChange={(e) => setSlot(i, { starts: e.target.value })} />
            <Field label="To" type="time" value={slot.ends} onChange={(e) => setSlot(i, { ends: e.target.value })} />
            <Field label="Name" optional maxLength={80} value={slot.title ?? ""} onChange={(e) => setSlot(i, { title: e.target.value })} />
            <Button type="button" variant="outline" size="icon" aria-label={`Remove slot ${i + 1}`} onClick={() => setSlots(slots.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden className="size-5" />
            </Button>
          </div>
        ))}
        {fields.slots && <p className="text-sm font-semibold text-destructive">{fields.slots}</p>}
        <Button type="button" variant="ghost" className="self-start" disabled={slots.length >= 21} onClick={() => setSlots([...slots, { weekday: "monday", starts: "18:00", ends: "20:00", title: "" }])}>
          <Plus aria-hidden className="size-4" /> Add a slot
        </Button>
      </fieldset>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-semibold">Where we usually train</legend>
        <SelectField
          label="Place"
          options={[
            { value: "none", label: "Not set" },
            { value: "venue", label: "One of our venues" },
            { value: "point", label: "A point on the map" },
          ]}
          value={place}
          onChange={(value) => setPlace(value as Place)}
        />
        {place === "venue" && (
          <SelectField label="Venue" options={(venues.data ?? []).map((v) => ({ value: v.id, label: v.name }))} value={venue} onChange={setVenue} error={fields.venue_id} hint="Check-in works when the venue has a position on the map." />
        )}
        {place === "point" && (
          <>
            <Field label="Name of the place" maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} hint="Members see this name, never the coordinates." />
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="outline" disabled={here.isPending} onClick={() => here.mutate()}>
                <MapPin aria-hidden className="size-4" /> {here.isPending ? "Finding where you are…" : "Use where I am now"}
              </Button>
              <span className="text-sm text-muted-foreground">{point ? `Set: ${point.latitude}, ${point.longitude}` : "Stand at the training place and tap the button."}</span>
            </div>
            {here.isError && <FormAlert>{here.error instanceof Error ? here.error.message : "We couldn't find where you are."}</FormAlert>}
            {fields.latitude && <p className="text-sm font-semibold text-destructive">{fields.latitude}</p>}
          </>
        )}
      </fieldset>

      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-1 font-semibold">Checking in</legend>
        <Field label="Opens before the start (minutes)" type="number" min={0} max={180} inputMode="numeric" value={before} onChange={(e) => setBefore(e.target.value)} error={fields.opens_before_minutes} />
        <Field label="Closes after the start (minutes)" type="number" min={5} max={240} inputMode="numeric" value={after} onChange={(e) => setAfter(e.target.value)} error={fields.closes_after_minutes} />
        <Field label="Late after (minutes)" type="number" min={0} max={240} inputMode="numeric" value={late} onChange={(e) => setLate(e.target.value)} error={fields.late_after_minutes} />
        <Field label="How close (metres)" type="number" min={25} max={MAX_CHECK_IN_RADIUS} inputMode="numeric" value={radius} onChange={(e) => setRadius(e.target.value)} error={fields.radius_m} hint={`At most ${MAX_CHECK_IN_RADIUS} m. Smaller is stricter.`} />
      </fieldset>

      {save.isError && !Object.keys(fields).length && <FormAlert>{errorMessage(save.error, "We couldn't save the rules.")}</FormAlert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || (place === "point" && !point)}>
          {save.isPending ? "Saving…" : "Save rules"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
