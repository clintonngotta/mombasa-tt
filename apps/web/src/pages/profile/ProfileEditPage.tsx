import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { Toggle } from "@/components/forms/Toggle"
import { LocationFields } from "@/components/forms/LocationFields"
import { AvatarField } from "@/components/profile/AvatarField"
import { BioField } from "@/components/profile/BioField"
import { ApiError, errorMessage } from "@/lib/api"
import { meQueryKey, useMe } from "@/lib/session"
import { updateAccount } from "@/lib/auth"
import {
  DETAIL_LABEL,
  EXPERIENCE,
  GOALS,
  GRIPS,
  HANDS,
  PUBLISHED_DETAILS,
  getProfile,
  playerKeys,
  profileKeys,
  saveGoals,
  updateProfile,
  type Profile,
} from "@/lib/profile"

const DETAIL_OPTIONS = PUBLISHED_DETAILS.map((value) => ({ value, label: DETAIL_LABEL[value] }))

export function ProfileEditPage() {
  const profile = useQuery({ queryKey: profileKeys.me, queryFn: getProfile })

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/profile">Profile</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Edit profile</h1>
        <p className="text-muted-foreground">Only your display name is required. Details stay private unless you publish them below.</p>
      </div>
      {profile.isPending && <p className="text-muted-foreground">Loading your profile…</p>}
      {profile.isError && <FormAlert>{errorMessage(profile.error, "We couldn't load your profile.")}</FormAlert>}
      {profile.data && <AvatarField avatar={profile.data.avatar} />}
      {profile.data && <ProfileForm initial={profile.data} />}
      <SignInPhone />
    </div>
  )
}

function ProfileForm({ initial }: { initial: Profile }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initial)
  const set = (patch: Partial<Profile>) => setForm((prev) => ({ ...prev, ...patch }))

  const save = useMutation({
    mutationFn: async (next: Profile) => {
      // goals and the photo go through their own endpoints; onboarding_completed is read-only.
      const { goals, onboarding_completed: _readOnly, avatar: _photo, ...fields } = next
      await updateProfile(fields)
      await saveGoals(goals)
    },
    // Refresh even on failure: the profile PATCH may have saved before the goals PUT failed.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: profileKeys.me }),
        queryClient.invalidateQueries({ queryKey: meQueryKey }),
        queryClient.invalidateQueries({ queryKey: playerKeys.all }),
      ]),
    onSuccess: () => navigate("/profile"),
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    save.mutate({
      ...form,
      display_name: form.display_name.trim(),
      nickname: form.nickname.trim(),
      style: form.style.trim(),
      // Leaving the directory unpublishes everything, so opting back in never silently republishes (REQ-006).
      published_details: form.directory_opt_in ? form.published_details : [],
    })
  }

  const fields = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const hasFieldErrors = Object.keys(fields).length > 0

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-6">
      <Field
        label="Display name"
        autoComplete="name"
        maxLength={80}
        value={form.display_name}
        onChange={(e) => set({ display_name: e.target.value })}
        error={fields.display_name}
      />
      <Field label="Nickname" optional maxLength={40} value={form.nickname} onChange={(e) => set({ nickname: e.target.value })} error={fields.nickname} />
      <LocationFields value={form} onChange={set} errors={fields} />
      <ChoiceGroup
        legend="Playing hand"
        optional
        options={HANDS}
        value={form.hand}
        onChange={(hand) => set({ hand })}
        onClear={() => set({ hand: "" })}
        error={fields.hand}
      />
      <ChoiceGroup
        legend="Grip"
        optional
        columns={3}
        options={GRIPS}
        value={form.grip}
        onChange={(grip) => set({ grip })}
        onClear={() => set({ grip: "" })}
        error={fields.grip}
      />
      <Field
        label="Playing style"
        optional
        maxLength={80}
        placeholder="e.g. Offensive looper, all-round, chopper"
        value={form.style}
        onChange={(e) => set({ style: e.target.value })}
        error={fields.style}
      />
      <ChoiceGroup
        legend="Experience"
        optional
        options={EXPERIENCE}
        value={form.experience}
        onChange={(experience) => set({ experience })}
        onClear={() => set({ experience: "" })}
        error={fields.experience}
      />
      <BioField value={form.bio} onChange={(bio) => set({ bio })} error={fields.bio} />

      <section aria-labelledby="visibility-heading" className="flex flex-col gap-4">
        <h2 id="visibility-heading" className="text-xl font-bold">
          What other players see
        </h2>
        <Toggle
          checked={form.directory_opt_in}
          onChange={(directory_opt_in) => set({ directory_opt_in })}
          label="List me in the player directory"
          description="Other players can find your name, nickname and clubs. Your email, contact details and location are never shown."
        />
        {form.directory_opt_in && (
          <ChoiceGroup
            multiple
            legend="Also show on my player page"
            optional
            options={DETAIL_OPTIONS}
            value={form.published_details}
            onChange={(published_details) => set({ published_details })}
            error={fields.published_details}
          />
        )}
      </section>

      <ChoiceGroup
        multiple
        legend="Your goals"
        optional
        options={GOALS}
        value={form.goals}
        onChange={(goals) => set({ goals })}
        error={fields.goals}
      />
      <p className="-mt-4 text-sm text-muted-foreground">Goals only arrange your Home shortcuts. They don't give you club roles or change your rating.</p>

      {save.isError && !hasFieldErrors && <FormAlert>{errorMessage(save.error, "We couldn't save your profile. Try again.")}</FormAlert>}
      {hasFieldErrors && <FormAlert>Check the highlighted fields.</FormAlert>}
      <Button type="submit" size="lg" disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save profile"}
      </Button>
    </form>
  )
}

/** The sign-in phone (REQ-003): players log in with their email or this number. */
function SignInPhone() {
  const queryClient = useQueryClient()
  const me = useMe()
  const [phone, setPhone] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => updateAccount({ phone: (phone ?? "").trim() }),
    onSuccess: (user) => {
      queryClient.setQueryData(meQueryKey, user)
      setPhone(null)
    },
  })
  if (!me.data) return null
  const value = phone ?? me.data.phone ?? ""
  const fields = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  return (
    <form
      noValidate
      aria-labelledby="sign-in-phone"
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault()
        save.mutate()
      }}
    >
      <h2 id="sign-in-phone" className="text-xl font-bold">
        Log in with your phone
      </h2>
      <Field
        label="Phone number"
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        optional
        value={value}
        onChange={(e) => setPhone(e.target.value)}
        error={fields.phone}
        hint="Log in with this number or your email. Only you see it."
      />
      {save.isError && !fields.phone && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      {save.isSuccess && phone === null && (
        <p role="status" className="text-sm font-semibold text-success">
          Saved.
        </p>
      )}
      <Button type="submit" variant="outline" className="self-start" disabled={save.isPending || phone === null || value.trim() === (me.data.phone ?? "")}>
        {save.isPending ? "Saving…" : "Save phone"}
      </Button>
    </form>
  )
}
