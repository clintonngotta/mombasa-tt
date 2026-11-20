import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, NotebookPen } from "lucide-react"
import { listMatchNotes, matchNoteKeys } from "@/lib/matchNotes"

/** Notes the player wrote on official matches (REQ-025), each leading back to its match: the recap
 * entry point. Notes on self-recorded matches live with those matches. */
export function OfficialMatchNotes() {
  const notes = useQuery({ queryKey: matchNoteKeys.list, queryFn: listMatchNotes })
  const official = (notes.data?.results ?? []).filter((note) => note.kind === "official" && note.tournament_id && note.event_id)
  if (official.length === 0) return null
  return (
    <section aria-labelledby="official-notes-heading" className="flex flex-col gap-3">
      <h2 id="official-notes-heading" className="flex items-center gap-2 text-xl font-bold">
        <NotebookPen aria-hidden className="size-5 text-brand-blue" /> My notes on tournament matches
      </h2>
      <ul className="flex flex-col gap-2">
        {official.map((note) => (
          <li key={note.id}>
            <Link
              to={`/tournaments/${note.tournament_id}/events/${note.event_id}/matches/${note.match_id}`}
              className="flex min-h-12 items-center gap-3 rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold break-words">{note.title}</span>
                <span className="text-sm text-muted-foreground">{note.tournament_name}</span>
                {note.goals && <span className="line-clamp-2 text-sm">Work on: {note.goals}</span>}
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
