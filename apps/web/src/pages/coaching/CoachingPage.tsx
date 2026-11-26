import { Link } from "react-router-dom"
import { Search } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"
import { CoachingTab } from "@/pages/coaching/CoachingTab"

/** A coach's own page (REQ-047): requests waiting for them, their trainees, session requests and their
 * week, and their profile. The coach is still a player, so Play, Training and their record stay in the menu. */
export function CoachingPage() {
  return (
    <div className="flex max-w-[1080px] flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">Coaching</h1>
          <p className="text-muted-foreground">Your trainees, their tasks, session requests and your calendar as a coach.</p>
        </div>
        <Link to="/coaches" className={buttonVariants({ variant: "outline" })}>
          <Search aria-hidden className="size-5" /> Find a coach
        </Link>
      </div>
      <CoachingTab />
    </div>
  )
}
