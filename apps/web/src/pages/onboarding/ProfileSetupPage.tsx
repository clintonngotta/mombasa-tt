import { useEffect, useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { OnboardingLayout } from "@/components/layout/OnboardingLayout"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { BioField } from "@/components/profile/BioField"
import { errorMessage } from "@/lib/api"
import { isBlankProfile, useOnboardingDraft, type ProfileDraft } from "@/lib/onboarding"
import { EXPERIENCE, GRIPS, HANDS, getProfile, profileKeys, updateProfile } from "@/lib/profile"

export function ProfileSetupPage() {
  const navigate = useNavigate()
  const [draft, updateDraft] = useOnboardingDraft()
  const profile = draft.profile
  const [nameError, setNameError] = useState<string>()

  // Resuming on another device, or after this one's storage was cleared: start from what the server
  // already has (at least the display name from sign-up) instead of an empty form.
  const saved = useQuery({ queryKey: profileKeys.me, queryFn: getProfile, enabled: isBlankProfile(profile) }).data
  useEffect(() => {
    if (!saved || !isBlankProfile(profile)) return
    const { display_name, nickname, hand, grip, style, experience, bio } = saved
    updateDraft({ profile: { display_name, nickname, hand, grip, style, experience, bio }, directoryOptIn: saved.directory_opt_in, goals: saved.goals })
  }, [saved, profile, updateDraft])

  const setProfile = (patch: Partial<ProfileDraft>) => updateDraft({ profile: { ...profile, ...patch } })

  const mutation = useMutation({
    mutationFn: (profile: ProfileDraft) => updateProfile(profile),
    onSuccess: () => navigate("/onboarding/community"),
  })

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!profile.display_name.trim()) {
      setNameError("Enter the name other players will see.")
      return
    }
    mutation.mutate({ ...profile, display_name: profile.display_name.trim() })
  }

  return (
    <OnboardingLayout
      step={1}
      title="Set up your profile"
      description="Only your display name is required. Everything else stays private until you choose to publish it."
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-6">
        {mutation.isError && <FormAlert>{errorMessage(mutation.error, "We couldn't save your profile. Your answers are kept on this device; try again.")}</FormAlert>}

        <Field
          label="Display name"
          autoComplete="name"
          value={profile.display_name}
          onChange={(e) => {
            setNameError(undefined)
            setProfile({ display_name: e.target.value })
          }}
          error={nameError}
        />
        <Field
          label="Nickname"
          optional
          value={profile.nickname}
          onChange={(e) => setProfile({ nickname: e.target.value })}
        />

        <ChoiceGroup legend="Playing hand" optional options={HANDS} value={profile.hand} onChange={(hand) => setProfile({ hand })} />
        <ChoiceGroup legend="Grip" optional columns={3} options={GRIPS} value={profile.grip} onChange={(grip) => setProfile({ grip })} />
        <Field
          label="Playing style"
          optional
          placeholder="e.g. Offensive looper, all-round, chopper"
          value={profile.style}
          onChange={(e) => setProfile({ style: e.target.value })}
        />
        <ChoiceGroup
          legend="Experience"
          optional
          options={EXPERIENCE}
          value={profile.experience}
          onChange={(experience) => setProfile({ experience })}
        />

        <BioField value={profile.bio} onChange={(bio) => setProfile({ bio })} />

        <Button type="submit" size="lg" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Continue"}
        </Button>
      </form>
    </OnboardingLayout>
  )
}
