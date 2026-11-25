import { Link } from "react-router-dom"
import { LocateFixed, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { formatDistance, RADII, type NearMe } from "@/lib/nearby"
import { cn } from "@/lib/utils"

/** Clubs or places to play: the two finders share one search, so each links to the other. */
export function FinderTabs({ current }: { current: "clubs" | "facilities" }) {
  const tabs = [
    { key: "clubs", to: "/club/find", label: "Clubs" },
    { key: "facilities", to: "/facilities", label: "Places to play" },
  ] as const
  return (
    <nav aria-label="What to find" className="flex w-fit rounded-lg border bg-card p-1">
      {tabs.map((tab) => (
        <Link
          key={tab.key}
          to={tab.to}
          aria-current={tab.key === current ? "page" : undefined}
          className={cn(
            "flex h-12 items-center rounded-md px-4 font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            tab.key === current && "bg-surface-selected text-brand-blue",
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  )
}

/** The "Near me" button, and once a position is known, how far to look. */
export function NearMeControls({ near, what }: { near: NearMe; what: string }) {
  if (!near.position) {
    return (
      <div className="flex flex-col gap-2">
        <Button type="button" variant="outline" className="self-start" disabled={near.locating} onClick={near.start}>
          <LocateFixed aria-hidden className="size-5" /> {near.locating ? "Finding your location…" : "Near me"}
        </Button>
        {near.error && <FormAlert>{near.error}</FormAlert>}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3 rounded-lg bg-surface-selected p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-semibold">
          <LocateFixed aria-hidden className="size-5 text-brand-blue" /> {what} near you
        </p>
        <Button type="button" variant="ghost" onClick={near.stop}>
          <X aria-hidden className="size-4" /> Stop
        </Button>
      </div>
      <div role="group" aria-label="How far to look" className="flex flex-wrap gap-2">
        {RADII.map((radius) => (
          <button
            key={radius}
            type="button"
            aria-pressed={near.radius === radius}
            onClick={() => near.setRadius(radius)}
            className={cn(
              "h-12 min-w-16 rounded-lg border bg-card px-3 font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              near.radius === radius && "border-brand-blue bg-brand-blue text-white",
            )}
          >
            {formatDistance(radius)}
          </button>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        {near.position.accuracy > near.radius
          ? `Your device placed you to within about ${formatDistance(near.position.accuracy)}, so a ${formatDistance(near.radius)} search may miss places. Try a wider distance. `
          : ""}
        Your location is used for this search only. It isn't saved or shown to anyone.{" "}
        <button type="button" className="font-semibold text-brand-blue underline" disabled={near.locating} onClick={near.start}>
          {near.locating ? "Updating…" : "Update my location"}
        </button>
      </p>
      {near.error && <FormAlert>{near.error}</FormAlert>}
    </div>
  )
}
