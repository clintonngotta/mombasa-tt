import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { OnboardingLayout } from "@/components/layout/OnboardingLayout"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { errorMessage } from "@/lib/api"
import { saveProfile, useOnboardingDraft, type Experience, type Grip, type Hand, type ProfileDraft } from "@/lib/onboarding"

const HANDS: { value: Hand; label: string }[] = [
  { value: "right", label: "Right-handed" },
  { value: "left", label: "Left-handed" },
]

const GRIPS: { value: Grip; label: string }[] = [
  { value: "shakehand", label: "Shakehand" },
  { value: "penhold", label: "Penhold" },
  { value: "other", label: "Other" },
]

const EXPERIENCE: { value: Experience; label: string; description: string }[] = [
  { value: "new", label: "New to the game", description: "Learning the basics" },
  { value: "casual", label: "Casual", description: "Play for fun now and then" },
  { value: "club", label: "Club player", description: "Play regularly at a club" },
  { value: "competitive", label: "Competitive", description: "Enter leagues or tournaments" },
]

export function ProfileSetupPage() {
  const navigate = useNavigate()
  const [draft, updateDraft] = useOnboardingDraft()
  const profile = draft.profile
  const [nameError, setNameError] = useState<string>()

  const setProfile = (patch: Partial<ProfileDraft>) => updateDraft({ profile: { ...profile, ...patch } })

  const mutation = useMutation({
    mutationFn: saveProfile,
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

        <div className="flex flex-col gap-2">
          <Label htmlFor="bio" className="text-base font-semibold">
            Bio <span className="font-normal text-muted-foreground">(optional)</span>
          </Label>
          <textarea
            id="bio"
            rows={3}
            maxLength={280}
            value={profile.bio}
            onChange={(e) => setProfile({ bio: e.target.value })}
            className="w-full rounded-lg border border-input bg-card px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <p className="text-sm text-muted-foreground tabular">{profile.bio.length}/280</p>
        </div>

        <Button type="submit" size="lg" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Continue"}
        </Button>
      </form>
    </OnboardingLayout>
  )
}
