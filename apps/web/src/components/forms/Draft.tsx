import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { Draft } from "./useDraft"

const savedTime = (at: number) => new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(at))

/**
 * "Save draft" beside a form's own button, with what is kept on this device and a way to drop it.
 * Forms whose own button already saves a draft on the server pass another label ("Finish later").
 */
export function DraftBar({ draft, label = "Save draft", className }: { draft: Draft; label?: string; className?: string }) {
  if (!draft.enabled) return null
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-2", className)}>
      <Button type="button" variant="outline" className="h-12 px-4 text-base" onClick={draft.save}>
        {label}
      </Button>
      <p role="status" className="min-w-0 flex-1 text-sm text-muted-foreground">
        {draft.failed
          ? "We couldn't keep this draft on this device. It may be too long, or the device's storage is full or switched off."
          : draft.savedAt === null
            ? "Keeps what you typed on this device so you can finish later."
            : draft.restored
              ? `You're continuing a draft saved ${savedTime(draft.savedAt)}.`
              : `Draft saved on this device, ${savedTime(draft.savedAt)}.`}
      </p>
      {draft.savedAt !== null && (
        <Button type="button" variant="ghost" className="h-12 px-3 text-base text-destructive" onClick={draft.discard}>
          Discard draft
        </Button>
      )}
    </div>
  )
}
