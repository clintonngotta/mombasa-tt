import { useNavigate } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { OnboardingLayout } from "@/components/layout/OnboardingLayout"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { completeOnboarding, useOnboardingDraft } from "@/lib/onboarding"
import { GOALS, saveGoals, type Goal } from "@/lib/profile"

export function GoalsPage() {
  const navigate = useNavigate()
  const [draft, updateDraft] = useOnboardingDraft()

  const finish = useMutation({
    mutationFn: async (goals: Goal[]) => {
      await saveGoals(goals)
      await completeOnboarding()
    },
    onSuccess: () => navigate("/onboarding/complete"),
  })

  return (
    <OnboardingLayout
      step={3}
      backTo="/onboarding/community"
      title="What brings you here?"
      description="Pick any that apply. Goals only arrange your Home shortcuts; they don't give you club roles or change your rating."
    >
      <ChoiceGroup
        multiple
        legend="Your goals"
        optional
        options={GOALS}
        value={draft.goals}
        onChange={(goals) => updateDraft({ goals })}
      />

      {finish.isError && <FormAlert>{errorMessage(finish.error, "We couldn't save your goals. Try again.")}</FormAlert>}
      <div className="flex flex-col gap-3">
        <Button size="lg" disabled={finish.isPending} onClick={() => finish.mutate(draft.goals)}>
          {finish.isPending ? "Saving…" : "Finish setup"}
        </Button>
        {draft.goals.length > 0 && (
          <Button variant="ghost" size="lg" disabled={finish.isPending} onClick={() => finish.mutate([])}>
            Skip goals
          </Button>
        )}
      </div>
    </OnboardingLayout>
  )
}
