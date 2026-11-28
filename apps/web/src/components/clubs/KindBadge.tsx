import { KIND_LABEL, type OrganizationKind } from "@/lib/clubs"
import { cn } from "@/lib/utils"

/** Short words for a badge beside an organization's name: a club, a team, a facility and so on. */
export const KIND_BADGE: Record<OrganizationKind, string> = {
  ...KIND_LABEL,
  club_facility: "Club · Facility",
  coaching: "Coaching",
}

/** Says what an organization is wherever its name shows (REQ-057): two of them may share a name. */
export function KindBadge({ kind, className }: { kind: OrganizationKind | undefined; className?: string }) {
  if (!kind) return null
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs leading-4 font-semibold whitespace-nowrap",
        kind === "team" ? "border-brand-gold/40 bg-brand-gold/10 text-foreground" : "border-brand-blue/30 bg-brand-blue/10 text-brand-blue",
        className,
      )}
    >
      {KIND_BADGE[kind]}
    </span>
  )
}

/** An organization's name with its kind beside it, for headings and lines of text. */
export function OrganizationName({ organization, className }: { organization: { name: string; kind?: OrganizationKind }; className?: string }) {
  return (
    <span className={cn("inline-flex min-w-0 flex-wrap items-center gap-2", className)}>
      <span className="min-w-0 break-words">{organization.name}</span>
      <KindBadge kind={organization.kind} />
    </span>
  )
}
