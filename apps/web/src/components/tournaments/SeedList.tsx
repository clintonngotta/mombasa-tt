import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type Announcements, type DragEndEvent } from "@dnd-kit/core"
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { ArrowDown, ArrowUp, GripVertical, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type Props = {
  /** Entry ids, best first. */
  seeds: string[]
  title: (id: string) => string
  onChange: (seeds: string[]) => void
}

/**
 * The seeds in order. A row is dragged by its handle (pointer, touch or keyboard: Space, arrows, Space),
 * so the rest of the row still scrolls the page; the arrows move it one place at a time.
 */
export function SeedList({ seeds, title, onChange }: Props) {
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }))
  const place = (id: string | number) => seeds.indexOf(String(id)) + 1
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${title(String(active.id))}, seed ${place(active.id)} of ${seeds.length}.`,
    onDragOver: ({ active, over }) => (over ? `${title(String(active.id))} is over seed ${place(over.id)} of ${seeds.length}.` : undefined),
    onDragEnd: ({ active, over }) => (over ? `${title(String(active.id))} is now seed ${place(over.id)} of ${seeds.length}.` : `${title(String(active.id))} was put back.`),
    onDragCancel: ({ active }) => `${title(String(active.id))} was put back as seed ${place(active.id)}.`,
  }

  function dropped({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return
    onChange(arrayMove(seeds, seeds.indexOf(String(active.id)), seeds.indexOf(String(over.id))))
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={dropped}
      accessibility={{ announcements, screenReaderInstructions: { draggable: "Press Space to pick this seed up, the arrow keys to move it, Space to drop it and Escape to put it back." } }}
    >
      <SortableContext items={seeds} strategy={verticalListSortingStrategy}>
        <ol className="flex flex-col gap-2" aria-label="Seeds in order">
          {seeds.map((id, index) => (
            <SeedRow
              key={id}
              id={id}
              number={index + 1}
              title={title(id)}
              first={index === 0}
              last={index === seeds.length - 1}
              onMove={(by) => onChange(arrayMove(seeds, index, index + by))}
              onRemove={() => onChange(seeds.filter((seed) => seed !== id))}
            />
          ))}
        </ol>
      </SortableContext>
    </DndContext>
  )
}

function SeedRow({ id, number, title, first, last, onMove, onRemove }: { id: string; number: number; title: string; first: boolean; last: boolean; onMove: (by: number) => void; onRemove: () => void }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id })
  return (
    <li
      ref={setNodeRef}
      // The list only moves up and down, so the row never slides sideways under the finger.
      style={{ transform: CSS.Translate.toString(transform && { ...transform, x: 0 }), transition }}
      className={cn("flex min-h-12 items-center gap-1 rounded-lg border bg-card", isDragging && "relative z-10 border-brand-blue shadow-lg")}
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Drag ${title}, seed ${number}`}
        className="flex size-12 shrink-0 cursor-grab touch-none items-center justify-center rounded-lg text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing"
      >
        <GripVertical aria-hidden className="size-5" />
      </button>
      <span className="w-6 font-semibold tabular-nums">{number}</span>
      <span className="min-w-0 flex-1 break-words">{title}</span>
      <Button variant="ghost" size="icon" aria-label={`Move ${title} up`} disabled={first} onClick={() => onMove(-1)}>
        <ArrowUp aria-hidden className="size-5" />
      </Button>
      <Button variant="ghost" size="icon" aria-label={`Move ${title} down`} disabled={last} onClick={() => onMove(1)}>
        <ArrowDown aria-hidden className="size-5" />
      </Button>
      <Button variant="ghost" size="icon" aria-label={`Unseed ${title}`} onClick={onRemove}>
        <X aria-hidden className="size-5" />
      </Button>
    </li>
  )
}
