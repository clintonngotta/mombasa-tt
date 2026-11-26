import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { Toggle } from "@/components/forms/Toggle"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import {
  coachingKeys,
  getMyCoachProfileOrNull,
  saveAvailability,
  saveCoachProfile,
  WEEKDAYS,
  type Availability,
  type CoachLevel,
  type CoachProfile,
} from "@/lib/coaching"
import { LEVEL_LABEL, SKILL_LABEL, SKILLS, type Skill } from "@/lib/training"

/** Set up or change a coach profile and the weekly hours players can book (REQ-047). */
export function CoachProfilePage() {
  const profile = useQuery({
    queryKey: coachingKeys.profile,
    queryFn: getMyCoachProfileOrNull,
  })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/training?tab=coaching">Coaching</BackLink>
      <h1 className="text-[32px] leading-9 font-bold">{profile.data ? "Your coach profile" : "Become a coach"}</h1>
      {profile.isError && <FormAlert>{errorMessage(profile.error)}</FormAlert>}
      {profile.isSuccess && <ProfileForm profile={profile.data} />}
    </div>
  )
}

type Window = { weekday: string; starts: string; ends: string; venue: string }

const toWindow = (w: Availability): Window => ({ weekday: String(w.weekday), starts: w.starts.slice(0, 5), ends: w.ends.slice(0, 5), venue: w.venue ?? "" })

function ProfileForm({ profile }: { profile: CoachProfile | null }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { results: memberships } = useMemberships()
  const clubs = (memberships ?? []).filter((m) => !m.managedOnly)
  const [headline, setHeadline] = useState(profile?.headline ?? "")
  const [bio, setBio] = useState(profile?.bio ?? "")
  const [levels, setLevels] = useState<CoachLevel[]>(profile?.levels ?? [])
  const [specialties, setSpecialties] = useState<Skill[]>((profile?.specialties ?? []) as Skill[])
  const [rate, setRate] = useState(profile?.rate_minor != null ? String(profile.rate_minor / 100) : "")
  const [town, setTown] = useState(profile?.town ?? "")
  const [firm, setFirm] = useState(profile?.firm_name ?? "")
  const [region, setRegion] = useState(profile?.region ?? "")
  const [accepting, setAccepting] = useState(profile?.accepting ?? true)
  const [orgIds, setOrgIds] = useState<string[]>(profile?.organizations.map((o) => o.id) ?? [])
  const [windows, setWindows] = useState<Window[]>(profile?.availability.map(toWindow) ?? [])
  const [missing, setMissing] = useState(false)

  const save = useMutation({
    mutationFn: async () => {
      const amount = rate.trim() === "" ? null : Math.round(Number(rate) * 100)
      await saveCoachProfile({
        headline: headline.trim(),
        bio: bio.trim(),
        levels,
        specialties,
        rate_minor: amount,
        town: town.trim(),
        region: region.trim(),
        firm_name: firm.trim(),
        accepting,
        organization_ids: orgIds,
      })
      return saveAvailability(windows.map((w) => ({ weekday: Number(w.weekday), starts: w.starts, ends: w.ends, venue: w.venue.trim() })))
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: coachingKeys.all })
      navigate("/training?tab=coaching")
    },
  })
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const badRate = rate.trim() !== "" && !(Number(rate) >= 0)

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const incomplete = !headline.trim() || badRate || windows.some((w) => !w.starts || !w.ends || w.ends <= w.starts)
    setMissing(incomplete)
    if (!incomplete) save.mutate()
  }

  const setWindow = (i: number, change: Partial<Window>) => setWindows(windows.map((w, j) => (j === i ? { ...w, ...change } : w)))

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-6">
      {save.isError && <FormAlert>{errorMessage(save.error, "We couldn't save your profile.")}</FormAlert>}
      {missing && <FormAlert>Add a headline, and give each window an end after its start.</FormAlert>}
      <Field
        label="Headline"
        maxLength={120}
        value={headline}
        onChange={(e) => setHeadline(e.target.value)}
        error={fields.headline}
        placeholder="e.g. ITTF level 1 coach, juniors and footwork"
        hint="One line players see in the list of coaches."
      />
      <Field
        label="Company, firm or academy"
        optional
        maxLength={120}
        value={firm}
        onChange={(e) => setFirm(e.target.value)}
        error={fields.firm_name}
        placeholder="e.g. Coast Spin Academy"
        hint="If you coach through a company, you can organize tournaments in its name."
      />
      <TextAreaField label="About you" optional rows={4} maxLength={2000} value={bio} onChange={(e) => setBio(e.target.value)} error={fields.bio} />
      <ChoiceGroup
        multiple
        legend="Levels you coach"
        optional
        columns={3}
        options={(["beginner", "intermediate", "advanced"] as CoachLevel[]).map((l) => ({ value: l, label: LEVEL_LABEL[l] }))}
        value={levels}
        onChange={setLevels}
      />
      <ChoiceGroup multiple legend="Specialities" optional columns={3} options={SKILLS.map((s) => ({ value: s, label: SKILL_LABEL[s] }))} value={specialties} onChange={setSpecialties} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Rate per hour (KES)" optional inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} error={badRate ? "Enter an amount, or leave it empty." : fields.rate_minor} />
        <Field label="Town" optional maxLength={80} value={town} onChange={(e) => setTown(e.target.value)} />
        <Field label="County or region" optional maxLength={100} value={region} onChange={(e) => setRegion(e.target.value)} />
      </div>
      {clubs.length > 0 && (
        <>
          <ChoiceGroup
            multiple
            legend="Clubs where you coach"
            optional
            options={clubs.map((m) => ({ value: m.organization.id, label: m.organization.name }))}
            value={orgIds}
            onChange={setOrgIds}
            error={fields.organization_ids}
          />
          <p className="-mt-4 text-sm text-muted-foreground">Their training timetable and tournaments appear in your calendar.</p>
        </>
      )}

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 text-base font-semibold">Weekly hours</legend>
        <p className="text-sm text-muted-foreground">Players book sessions inside these windows. Times are in {profile?.timezone ?? "Africa/Nairobi"}.</p>
        {windows.map((w, i) => (
          <div key={i} className="grid grid-cols-2 items-end gap-3 rounded-xl border bg-card p-3 sm:grid-cols-[1.2fr_1fr_1fr_1.5fr_auto]">
            <SelectField label="Day" options={WEEKDAYS.map((d, n) => ({ value: String(n), label: d }))} value={w.weekday} onChange={(value) => setWindow(i, { weekday: value })} />
            <Field label="From" type="time" value={w.starts} onChange={(e) => setWindow(i, { starts: e.target.value })} />
            <Field label="To" type="time" value={w.ends} onChange={(e) => setWindow(i, { ends: e.target.value })} />
            <Field label="Where" optional maxLength={120} value={w.venue} onChange={(e) => setWindow(i, { venue: e.target.value })} />
            <Button type="button" variant="outline" size="icon" aria-label={`Remove ${WEEKDAYS[Number(w.weekday)]} ${w.starts}`} onClick={() => setWindows(windows.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden className="size-5" />
            </Button>
          </div>
        ))}
        {fields.windows && <FormAlert>{fields.windows}</FormAlert>}
        <Button
          type="button"
          variant="outline"
          className="self-start"
          disabled={windows.length >= 42}
          onClick={() => setWindows([...windows, { weekday: windows.length ? windows[windows.length - 1].weekday : "0", starts: "16:00", ends: "19:00", venue: windows.at(-1)?.venue ?? "" }])}
        >
          <Plus aria-hidden className="size-4" /> Add hours
        </Button>
      </fieldset>

      <Toggle
        checked={accepting}
        onChange={setAccepting}
        label="Taking new players"
        description="When off, you're not listed and only your current trainees can book you."
      />
      <Button type="submit" size="lg" disabled={save.isPending}>
        {save.isPending ? "Saving…" : profile ? "Save" : "Create coach profile"}
      </Button>
    </form>
  )
}
