import { useQuery } from "@tanstack/react-query"
import { GraduationCap, Lock } from "lucide-react"
import { coachingKeys, listCoachNotes } from "@/lib/coaching"

/** What the player's coaches wrote about one of their matches (REQ-047). Only the player is served
 * these, so the section is empty, and hidden, for everyone else. */
export function CoachNotes({ kind, matchId }: { kind: "personal" | "official"; matchId: string }) {
  const notes = useQuery({ queryKey: coachingKeys.notes(kind, matchId), queryFn: () => listCoachNotes(kind, matchId) })
  if (!notes.data?.length) return null
  return (
    <section aria-labelledby="coach-notes-heading" className="flex flex-col gap-2">
      <h2 id="coach-notes-heading" className="flex items-center gap-2 text-xl">
        <GraduationCap aria-hidden className="size-5 text-brand-blue" /> Coach's notes
      </h2>
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Lock aria-hidden className="size-4" /> Only you see these.
      </p>
      <ul className="flex flex-col gap-2">
        {notes.data.map((note) => (
          <li key={note.id} className="rounded-xl border border-brand-blue/30 bg-card p-4">
            <p className="whitespace-pre-wrap">{note.body}</p>
            <p className="mt-2 text-sm text-muted-foreground">
              {note.coach.display_name} · {new Date(note.created_at).toLocaleDateString("en-KE", { day: "numeric", month: "short" })}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
