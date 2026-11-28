import { Ban, CircleCheck, CircleDot, FilePen, Hourglass, ListOrdered, LogOut, Megaphone, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { ENTRY_STATUS_LABEL, type EntryStatus } from "@/lib/entries"
import { EVENT_STATUS_LABEL, STATUS_LABEL, type EventStatus, type TournamentStatus } from "@/lib/tournaments"

type Look = { icon: LucideIcon; className: string }

// Status is always a word and an icon, never colour alone (REQ-002).
const LOOK: Record<TournamentStatus | "scheduled", Look> = {
  draft: { icon: FilePen, className: "border-border bg-muted text-muted-foreground" },
  published: { icon: Megaphone, className: "border-brand-blue/30 bg-surface-selected text-brand-blue" },
  scheduled: { icon: CircleDot, className: "border-border bg-muted text-muted-foreground" },
  in_progress: { icon: CircleDot, className: "border-brand-cyan bg-brand-cyan/15 text-brand-navy" },
  completed: { icon: CircleCheck, className: "border-success/30 bg-success/10 text-success" },
  cancelled: { icon: Ban, className: "border-destructive/30 bg-destructive/5 text-destructive" },
}

function Chip({ look, children }: { look: Look; children: string }) {
  const Icon = look.icon
  return (
    <span className={cn("inline-flex h-7 shrink-0 items-center gap-1 rounded-full border px-2.5 text-sm font-semibold", look.className)}>
      <Icon aria-hidden className="size-4" />
      {children}
    </span>
  )
}

export const TournamentStatusChip = ({ status }: { status: TournamentStatus }) => <Chip look={LOOK[status]}>{STATUS_LABEL[status]}</Chip>
export const EventStatusChip = ({ status }: { status: EventStatus }) => <Chip look={LOOK[status]}>{EVENT_STATUS_LABEL[status]}</Chip>

const ENTRY_LOOK: Record<EntryStatus, Look> = {
  pending: { icon: Hourglass, className: "border-border bg-muted text-muted-foreground" },
  accepted: { icon: CircleCheck, className: "border-success/30 bg-success/10 text-success" },
  waitlisted: { icon: ListOrdered, className: "border-brand-blue/30 bg-surface-selected text-brand-blue" },
  rejected: { icon: Ban, className: "border-destructive/30 bg-destructive/5 text-destructive" },
  withdrawn: { icon: LogOut, className: "border-border bg-muted text-muted-foreground" },
  pairing: { icon: CircleCheck, className: "border-border bg-muted text-muted-foreground" },
  replaced: { icon: LogOut, className: "border-border bg-muted text-muted-foreground" },
}

export const EntryStatusChip = ({ status }: { status: EntryStatus }) => <Chip look={ENTRY_LOOK[status]}>{ENTRY_STATUS_LABEL[status]}</Chip>
