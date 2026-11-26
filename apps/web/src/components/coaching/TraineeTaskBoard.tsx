import { useState } from "react"
import { Link } from "react-router-dom"
import { useQueries } from "@tanstack/react-query"
import { useSensors } from "@dnd-kit/core"
import { CircleCheck, Search } from "lucide-react"
import { KanbanBoard, KanbanCards, KanbanHeader, KanbanProvider } from "@/components/kibo-ui/kanban"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { errorMessage } from "@/lib/api"
import { coachingKeys, getTrainee, type Coaching } from "@/lib/coaching"
import { formatInstant } from "@/lib/dates"
import { LOCAL_TIME_ZONE } from "@/lib/training"
import { cn } from "@/lib/utils"

type Show = "open" | "done" | "all"
type Task = { id: string; name: string; column: string; plan: string; planTitle: string; kind: string; startsAt: string | null; done: boolean; overdue: boolean }
type Column = { id: string; name: string }

const SHOW: { value: Show; label: string }[] = [
  { value: "open", label: "To do" },
  { value: "done", label: "Done" },
  { value: "all", label: "All" },
]
/** A coach looks after a handful of players; past this the board asks them to open a player instead. */
const MAX_COLUMNS = 12

/** Tasks by player (REQ-047): one column per trainee, holding the items of the plans the coach gave them.
 * A card opens its plan, where the task is changed. Cards stay with their player: a task belongs to one
 * player's plan, so the cards are plain links, not the kanban's draggable cards. */
export function TraineeTaskBoard({ coachings }: { coachings: Coaching[] }) {
  const [search, setSearch] = useState("")
  const [show, setShow] = useState<Show>("open")
  const [now] = useState(() => Date.now())
  const sensors = useSensors() // none: the cards are not draggable
  const shown = coachings.slice(0, MAX_COLUMNS)
  const trainees = useQueries({
    queries: shown.map((c) => ({ queryKey: coachingKeys.trainee(c.id), queryFn: () => getTrainee(c.id), staleTime: 60_000 })),
  })
  if (coachings.length === 0) return null

  const term = search.trim().toLowerCase()
  const columns: Column[] = shown.map((c) => ({ id: c.id, name: c.trainee.display_name }))
  const tasks: Task[] = []
  const counts = new Map<string, { open: number; done: number }>()
  shown.forEach((coaching, index) => {
    const count = { open: 0, done: 0 }
    counts.set(coaching.id, count)
    for (const plan of trainees[index].data?.plans ?? []) {
      for (const item of plan.items) {
        const done = !!item.completed_at
        count[done ? "done" : "open"] += 1
        if ((show === "open" && done) || (show === "done" && !done)) continue
        if (term && !`${item.title} ${plan.title} ${item.drill_title ?? ""}`.toLowerCase().includes(term)) continue
        const due = item.ends_at ?? item.starts_at ?? null
        tasks.push({ id: item.id, name: item.title, column: coaching.id, plan: plan.id, planTitle: plan.title, kind: item.kind, startsAt: item.starts_at ?? null, done, overdue: !done && !!due && new Date(due).getTime() < now })
      }
    }
  })
  // To do: the earliest first, undated last. Done keeps the plans' own order.
  if (show !== "done") tasks.sort((a, b) => Number(a.done) - Number(b.done) || (a.startsAt ?? "9").localeCompare(b.startsAt ?? "9"))
  const failed = trainees.find((t) => t.isError)
  const loading = trainees.some((t) => t.isPending)

  return (
    <section aria-labelledby="tasks-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="tasks-heading" className="text-xl font-bold">
          Tasks by player
        </h2>
        <Segmented label="Which tasks" options={SHOW} value={show} onChange={setShow} />
      </div>
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input type="search" aria-label="Search tasks" placeholder="Search tasks, drills or plans" maxLength={80} className="pl-9" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      {failed && <FormAlert>{errorMessage(failed.error, "We couldn't load some players' tasks.")}</FormAlert>}
      {coachings.length > MAX_COLUMNS && (
        <p className="text-sm text-muted-foreground">
          Showing your first {MAX_COLUMNS} players. Open a player under Trainees for the rest.
        </p>
      )}
      <div className="-mx-1 overflow-x-auto px-1 pb-2">
        <KanbanProvider columns={columns} data={tasks} sensors={sensors} className="auto-cols-[minmax(15rem,1fr)] items-start gap-3">
          {(column) => {
            const count = counts.get(column.id) ?? { open: 0, done: 0 }
            const empty = !tasks.some((task) => task.column === column.id)
            return (
              <KanbanBoard key={column.id} id={column.id} className="size-auto max-h-[32rem] rounded-xl bg-card text-sm shadow-none ring-0">
                <KanbanHeader className="flex items-center justify-between gap-2 p-3">
                  <Link to={`/coaching/trainees/${column.id}`} className="min-w-0 truncate text-base outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
                    {column.name}
                  </Link>
                  <span className="shrink-0 text-xs font-normal text-muted-foreground">
                    {count.open} to do · {count.done} done
                  </span>
                </KanbanHeader>
                <KanbanCards<Task> id={column.id}>
                  {(task) => (
                    <div key={task.id} className="rounded-lg border bg-background">
                      <Link to={`/coaching/trainees/${task.column}/plans/${task.plan}`} className="flex flex-col gap-1 rounded-lg p-3 outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50">
                        <span className={cn("flex items-start gap-2 font-semibold", task.done && "text-muted-foreground line-through")}>
                          {task.done && <CircleCheck aria-label="Done" className="mt-0.5 size-4 shrink-0 text-success" />}
                          <span className="min-w-0 break-words">{task.name}</span>
                        </span>
                        <span className="text-xs text-muted-foreground">{task.planTitle}</span>
                        <span className={cn("text-xs", task.overdue ? "font-semibold text-destructive" : "text-muted-foreground")}>
                          {task.startsAt ? formatInstant(task.startsAt, LOCAL_TIME_ZONE) : "No date"}
                          {task.overdue && " · overdue"}
                        </span>
                      </Link>
                    </div>
                  )}
                </KanbanCards>
                {empty && (
                  <p className="p-3 text-sm text-muted-foreground">
                    {loading ? "Loading…" : count.open + count.done === 0 ? "No tasks yet. Give them a plan from their page." : "Nothing matches."}
                  </p>
                )}
              </KanbanBoard>
            )
          }}
        </KanbanProvider>
      </div>
    </section>
  )
}
