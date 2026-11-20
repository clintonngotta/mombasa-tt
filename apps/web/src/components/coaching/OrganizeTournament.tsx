import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { Trophy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { clubKeys, setActiveOrganization } from "@/lib/clubs"
import { openCoachOrganizer, type CoachProfile } from "@/lib/coaching"
import { cn } from "@/lib/utils"

/** A coach organizes a tournament in their own name or their firm's (REQ-047). The first time opens
 * their coaching desk, which then runs tournaments like a club does. */
export function OrganizeTournament({ profile }: { profile: CoachProfile }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const open = useMutation({
    mutationFn: openCoachOrganizer,
    onSuccess: async (desk, as) => {
      await queryClient.invalidateQueries({ queryKey: clubKeys.memberships })
      setActiveOrganization(desk.organization_id)
      navigate(`/club/tournaments/new?as=${as}`)
    },
  })
  const firm = profile.firm_name

  return (
    <section aria-labelledby="organize-heading" className={cn(ROW, "flex-wrap justify-between")}>
      <Trophy aria-hidden className="size-5 shrink-0 text-brand-blue" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span id="organize-heading" className="font-semibold">
          Organize a tournament
        </span>
        <span className="text-sm text-muted-foreground">
          {firm ? `Run it as yourself or as ${firm}.` : "Run it in your own name. Add your firm to your profile to organize as the firm."}
        </span>
      </span>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={open.isPending} onClick={() => open.mutate("coach")}>
          As myself
        </Button>
        {firm && (
          <Button type="button" variant="outline" disabled={open.isPending} onClick={() => open.mutate("firm")}>
            As {firm}
          </Button>
        )}
      </div>
      {open.isError && (
        <div className="w-full">
          <FormAlert>{errorMessage(open.error, "We couldn't open your coaching desk.")}</FormAlert>
        </div>
      )}
    </section>
  )
}
