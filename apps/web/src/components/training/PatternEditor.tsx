import { useState } from "react"
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { VirtualTable } from "@/components/training/VirtualTable"
import type { PatternStep } from "@/lib/training"
import { cn } from "@/lib/utils"

const LABELS = ["BH", "FH", "FH middle", "FH wide", "FH pivot", "BH block", "FH loop", "BH flick", "Push", "Short", "Serve"]
const MAX_STEPS = 12

/**
 * Builds a drill's pattern on the virtual table (REQ-026): choose a label, then click where the ball lands.
 * Balls on your half are what your partner sends you, labelled with the stroke you play from there; balls
 * on their half are your shots.
 */
export function PatternEditor({ steps, onChange, error }: { steps: PatternStep[]; onChange: (steps: PatternStep[]) => void; error?: string }) {
  const [label, setLabel] = useState("BH")
  const full = steps.length >= MAX_STEPS
  const set = (index: number, patch: Partial<PatternStep>) => onChange(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)))
  const move = (index: number, to: number) => {
    const next = [...steps]
    const [step] = next.splice(index, 1)
    next.splice(to, 0, step)
    onChange(next)
  }

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 font-semibold">
        Pattern on the table <span className="font-normal text-muted-foreground">(optional)</span>
      </legend>
      <p className="text-sm text-muted-foreground">
        Pick a label, then click where the ball lands. Your half is at the bottom; label those balls with the stroke you play from there. Up to {MAX_STEPS} balls.
      </p>
      <div role="group" aria-label="Label for the next ball" className="flex flex-wrap gap-2">
        {LABELS.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={label === option}
            onClick={() => setLabel(option)}
            className={cn(
              "h-10 rounded-full border px-3 text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              label === option ? "border-brand-blue bg-surface-selected text-brand-blue" : "bg-card text-muted-foreground",
            )}
          >
            {option}
          </button>
        ))}
        <Input aria-label="Or type a label" placeholder="Other label" maxLength={40} value={LABELS.includes(label) ? "" : label} onChange={(e) => setLabel(e.target.value)} className="h-10 w-36" />
      </div>
      <div className="flex flex-col items-start gap-4 sm:flex-row">
        <VirtualTable
          steps={steps}
          label="Pattern being drawn. Click a zone to place the next ball."
          onPick={
            full || !label.trim()
              ? undefined
              : ({ x, depth, side }) => onChange([...steps, { hitter: side === "near" ? "partner" : "you", stroke: label.trim(), x, depth, note: "" }])
          }
        />
        {steps.length > 0 && (
          <ol aria-label="Balls in order" className="flex w-full flex-col gap-2">
            {steps.map((step, i) => (
              <li key={i} className="flex flex-col gap-1 rounded-lg border bg-card p-2">
                <div className="flex items-center gap-1">
                  <span className="flex-1 text-sm font-semibold">
                    {i + 1} · {step.stroke}
                    <span className="font-normal text-muted-foreground"> · {step.hitter === "partner" ? "your side" : "partner's side"}, {step.depth}, {step.x === "center" ? "middle" : step.x}</span>
                  </span>
                  <Button type="button" variant="ghost" size="icon" aria-label={`Move ball ${i + 1} earlier`} disabled={i === 0} onClick={() => move(i, i - 1)}>
                    <ArrowUp aria-hidden className="size-4" />
                  </Button>
                  <Button type="button" variant="ghost" size="icon" aria-label={`Move ball ${i + 1} later`} disabled={i === steps.length - 1} onClick={() => move(i, i + 1)}>
                    <ArrowDown aria-hidden className="size-4" />
                  </Button>
                  <Button type="button" variant="ghost" size="icon" aria-label={`Remove ball ${i + 1}`} onClick={() => onChange(steps.filter((_, j) => j !== i))}>
                    <Trash2 aria-hidden className="size-4" />
                  </Button>
                </div>
                <Input aria-label={`Note for ball ${i + 1}`} placeholder="Note, e.g. partner blocks diagonally" maxLength={80} value={step.note ?? ""} onChange={(e) => set(i, { note: e.target.value })} className="h-9 text-sm" />
              </li>
            ))}
          </ol>
        )}
      </div>
      {full && <p className="text-sm text-muted-foreground">That's the most balls a pattern holds.</p>}
      {error && <p className="text-sm font-semibold text-destructive">{error}</p>}
    </fieldset>
  )
}
