import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import {
  can,
  clubKeys,
  getClubProfile,
  saveTrainingHours,
  updateOrganizationLocation,
  useActiveMembership,
  type ClubProfile,
} from "@/lib/clubs"
import { WEEKDAYS } from "@/lib/coaching"

const MAX_HOURS = 42
const NO_VENUE = "none"

/** What players looking for a club see: the description (roles.manage) and the weekly training hours
 * (training.manage). The rest of the profile comes from the club's location and venues. */
export function ClubProfileEditPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const editDescription = can(active, "roles.manage")
  const editHours = can(active, "training.manage")
  const allowed = editDescription || editHours
  const profile = useQuery({ queryKey: clubKeys.profile(orgId), queryFn: () => getClubProfile(orgId), enabled: allowed })

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Club profile</h1>
        <p className="text-muted-foreground">
          Players looking for a club see this, with your location, venues and coming tournaments.{" "}
          {orgId && (
            <Link to={`/club/find/${orgId}`} state={{ from: "/club/profile" }} className="font-semibold text-brand-blue underline">
              See it as they do
            </Link>
          )}
        </p>
      </div>
      {memberships.isSuccess && !allowed && <AccessLost />}
      {profile.isPending && allowed && <p className="text-muted-foreground">Loading…</p>}
      {profile.isError && <FormAlert>{errorMessage(profile.error, "We couldn't load the club profile.")}</FormAlert>}
      {profile.isSuccess && editDescription && <DescriptionForm club={profile.data} />}
      {profile.isSuccess && editHours && <TrainingHoursForm club={profile.data} />}
    </div>
  )
}

function DescriptionForm({ club }: { club: ClubProfile }) {
  const queryClient = useQueryClient()
  const [description, setDescription] = useState(club.description)
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () => updateOrganizationLocation(club.id, { description: description.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: clubKeys.all })
      setSaved(true)
    },
  })
  const fields = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  return (
    <form
      noValidate
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        setSaved(false)
        save.mutate()
      }}
    >
      <TextAreaField
        label="About the club"
        optional
        rows={5}
        maxLength={2000}
        value={description}
        onChange={(e) => {
          setDescription(e.target.value)
          setSaved(false)
        }}
        error={fields.description}
        hint="Who plays here, levels welcome, fees in a sentence, how to get started."
      />
      {save.isError && !fields.description && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      {saved && (
        <p role="status" className="text-sm text-success">
          Saved.
        </p>
      )}
      <Button type="submit" className="self-start" disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save description"}
      </Button>
    </form>
  )
}

type Slot = { weekday: string; starts: string; ends: string; label: string; venue: string }

function TrainingHoursForm({ club }: { club: ClubProfile }) {
  const queryClient = useQueryClient()
  const [slots, setSlots] = useState<Slot[]>(() =>
    club.training_hours.map((h) => ({
      weekday: String(h.weekday),
      starts: h.starts.slice(0, 5),
      ends: h.ends.slice(0, 5),
      label: h.label ?? "",
      venue: h.venue && club.venues.some((v) => v.id === h.venue) ? h.venue : NO_VENUE,
    })),
  )
  const [invalid, setInvalid] = useState(false)
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () =>
      saveTrainingHours(
        club.id,
        slots.map((s) => ({
          weekday: Number(s.weekday),
          starts: s.starts,
          ends: s.ends,
          label: s.label.trim(),
          venue: s.venue === NO_VENUE ? null : s.venue,
        })),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: clubKeys.all })
      setSaved(true)
    },
  })
  const venueOptions = [{ value: NO_VENUE, label: "Not set" }, ...club.venues.map((v) => ({ value: v.id, label: v.name }))]
  const setSlot = (i: number, change: Partial<Slot>) => {
    setSaved(false)
    setSlots(slots.map((s, j) => (j === i ? { ...s, ...change } : s)))
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const bad = slots.some((s) => !s.starts || !s.ends || s.ends <= s.starts)
    setInvalid(bad)
    setSaved(false)
    if (!bad) save.mutate()
  }

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-3">
      <h2 className="text-xl font-bold">Training hours</h2>
      <p className="text-sm text-muted-foreground">Weekly times when the club trains, in {club.timezone}. Leave the list empty to hide them.</p>
      {invalid && <FormAlert>Give each time an end after its start.</FormAlert>}
      {save.isError && <FormAlert>{errorMessage(save.error, "We couldn't save the training hours.")}</FormAlert>}
      {slots.map((s, i) => (
        <div key={i} className="grid grid-cols-2 items-end gap-3 rounded-xl border bg-card p-3 sm:grid-cols-[1.2fr_1fr_1fr_auto]">
          <SelectField label="Day" options={WEEKDAYS.map((d, n) => ({ value: String(n), label: d }))} value={s.weekday} onChange={(value) => setSlot(i, { weekday: value })} />
          <Field label="From" type="time" value={s.starts} onChange={(e) => setSlot(i, { starts: e.target.value })} />
          <Field label="To" type="time" value={s.ends} onChange={(e) => setSlot(i, { ends: e.target.value })} />
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={`Remove ${WEEKDAYS[Number(s.weekday)]} ${s.starts}`}
            onClick={() => {
              setSaved(false)
              setSlots(slots.filter((_, j) => j !== i))
            }}
          >
            <Trash2 aria-hidden className="size-5" />
          </Button>
          <div className="col-span-2 grid gap-3 sm:col-span-4 sm:grid-cols-2">
            <Field label="For" optional maxLength={80} placeholder="e.g. Juniors, Open play" value={s.label} onChange={(e) => setSlot(i, { label: e.target.value })} />
            <SelectField label="Venue" options={venueOptions} value={s.venue} onChange={(value) => setSlot(i, { venue: value })} />
          </div>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={slots.length >= MAX_HOURS}
          onClick={() => {
            const last = slots.at(-1)
            setSaved(false)
            setSlots([...slots, { weekday: last?.weekday ?? "0", starts: "17:00", ends: "19:00", label: "", venue: last?.venue ?? NO_VENUE }])
          }}
        >
          <Plus aria-hidden className="size-4" /> Add a time
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save training hours"}
        </Button>
      </div>
      {saved && (
        <p role="status" className="text-sm text-success">
          Training hours saved.
        </p>
      )}
    </form>
  )
}
