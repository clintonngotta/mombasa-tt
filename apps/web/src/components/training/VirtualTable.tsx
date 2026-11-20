import { useId } from "react"
import type { PatternStep } from "@/lib/training"
import { cn } from "@/lib/utils"

/*
 * A table seen from above (REQ-026), you at the bottom and your partner at the top, like a coach's
 * drawing. A pattern step is a ball landing: "partner" steps land on your half, "you" steps on theirs.
 * `x` is seen from you, so "right" is a right-hander's forehand side on both halves.
 */

type X = PatternStep["x"]
type Depth = PatternStep["depth"]
type Side = "near" | "far"

const W = 180
const H = 320
const TABLE = { x: 20, y: 25, w: 140, h: 270 }
const NET_Y = TABLE.y + TABLE.h / 2
const XS: Record<X, number> = { left: TABLE.x + 24, center: TABLE.x + TABLE.w / 2, right: TABLE.x + TABLE.w - 24 }
const YS: Record<Side, Record<Depth, number>> = {
  near: { short: NET_Y + 22, half: NET_Y + 66, long: TABLE.y + TABLE.h - 20 },
  far: { short: NET_Y - 22, half: NET_Y - 66, long: TABLE.y + 20 },
}
const ROWS: Depth[] = ["short", "half", "long"]
const COLUMNS: X[] = ["left", "center", "right"]

const sideOf = (step: Pick<PatternStep, "hitter">): Side => (step.hitter === "partner" ? "near" : "far")
const point = (step: PatternStep) => ({ x: XS[step.x], y: YS[sideOf(step)][step.depth] })

/** Where the ball was struck from: the previous landing, or the hitter's end for the first shot. */
function origin(steps: PatternStep[], index: number) {
  const step = steps[index]
  const before = steps[index - 1]
  if (before && sideOf(before) !== sideOf(step)) return point(before)
  return { x: W / 2, y: step.hitter === "partner" ? 6 : H - 6 }
}

function Table({ children, label }: { children: React.ReactNode; label?: string }) {
  return (
    <>
      {label && <title>{label}</title>}
      <rect x={TABLE.x - 3} y={TABLE.y - 3} width={TABLE.w + 6} height={TABLE.h + 6} rx="3" className="fill-white" />
      <rect x={TABLE.x} y={TABLE.y} width={TABLE.w} height={TABLE.h} rx="2" className="fill-[#2f7d4f]" />
      <line x1={TABLE.x + TABLE.w / 2} y1={TABLE.y} x2={TABLE.x + TABLE.w / 2} y2={TABLE.y + TABLE.h} className="stroke-white/80" strokeWidth="1.2" />
      <line x1={TABLE.x - 10} y1={NET_Y} x2={TABLE.x + TABLE.w + 10} y2={NET_Y} className="stroke-slate-700" strokeWidth="3" />
      <text x={W / 2} y={14} textAnchor="middle" className="fill-muted-foreground text-[9px]">
        Partner
      </text>
      <text x={W / 2} y={H - 4} textAnchor="middle" className="fill-muted-foreground text-[9px]">
        You
      </text>
      {children}
    </>
  )
}

function Arrow({ from, to, marker, faded }: { from: { x: number; y: number }; to: { x: number; y: number }; marker: string; faded?: boolean }) {
  // A gentle curve, like a ball's flight drawn from above.
  const bend = (to.x - from.x) * 0.15 + 12
  const cx = (from.x + to.x) / 2 + bend
  const cy = (from.y + to.y) / 2
  return (
    <path
      d={`M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`}
      fill="none"
      strokeWidth="1.5"
      strokeDasharray="3 2"
      markerEnd={`url(#${marker})`}
      className={cn("stroke-white", faded && "opacity-50")}
    />
  )
}

/** How many earlier balls landed on the same spot, so their labels stack instead of overlapping. */
function stackIndex(steps: PatternStep[], index: number) {
  const here = point(steps[index])
  return steps.slice(0, index).filter((other) => {
    const there = point(other)
    return there.x === here.x && there.y === here.y
  }).length
}

function Ball({ step, n, stack = 0 }: { step: PatternStep; n: number; stack?: number }) {
  const { x, y } = point(step)
  const label = `${n} ${step.stroke}`
  const width = Math.max(26, label.length * 5.6 + 10)
  // Above the ball, clear of the net and of earlier labels at this spot; below it at the far end.
  const lift = 22 + stack * 16
  const roomAbove = y - lift > TABLE.y + 2 && !(y > NET_Y && y - lift < NET_Y + 2)
  const above = roomAbove ? y - lift : y + 8 + stack * 16
  const left = Math.min(Math.max(x - width / 2, 2), W - width - 2)
  return (
    <g>
      <circle cx={x} cy={y} r="5" className="fill-[#f5a524] stroke-white" strokeWidth="1.2" />
      <rect x={left} y={above} width={width} height="14" rx="7" className="fill-white/95" />
      <text x={left + width / 2} y={above + 10} textAnchor="middle" className="fill-slate-900 text-[9px] font-semibold">
        {label}
      </text>
    </g>
  )
}

function ArrowHead({ id }: { id: string }) {
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" className="fill-white" />
      </marker>
    </defs>
  )
}

/** Every ball of a pattern on one table, numbered in order. With `onPick`, the 18 zones are buttons. */
export function VirtualTable({
  steps,
  onPick,
  pickSide,
  className,
  label = "Drill pattern on the table",
}: {
  steps: PatternStep[]
  onPick?: (place: { x: X; depth: Depth; side: Side }) => void
  /** Which half takes a click; both when unset. */
  pickSide?: Side
  className?: string
  label?: string
}) {
  const marker = useId().replace(/:/g, "")
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className={cn("h-auto w-full max-w-[280px]", className)}>
      <ArrowHead id={marker} />
      <Table>
        {steps.map((step, i) => (
          <Arrow key={`a${i}`} from={origin(steps, i)} to={point(step)} marker={marker} faded={i < steps.length - 1 && steps.length > 4} />
        ))}
        {steps.map((step, i) => (
          <Ball key={`b${i}`} step={step} n={i + 1} stack={stackIndex(steps, i)} />
        ))}
        {onPick &&
          (["far", "near"] as Side[])
            .filter((side) => !pickSide || side === pickSide)
            .flatMap((side) =>
              ROWS.flatMap((depth) =>
                COLUMNS.map((x) => {
                  const cell = { w: TABLE.w / 3, h: TABLE.h / 6 }
                  const cy = YS[side][depth]
                  const name = `${side === "near" ? "Your" : "Partner's"} side, ${depth}, ${x === "center" ? "middle" : x}`
                  return (
                    <rect
                      key={`${side}-${depth}-${x}`}
                      role="button"
                      tabIndex={0}
                      aria-label={`Place the ball: ${name}`}
                      x={XS[x] - cell.w / 2 + (x === "left" ? -4 : x === "right" ? 4 : 0)}
                      y={cy - cell.h / 2}
                      width={cell.w}
                      height={cell.h}
                      className="cursor-pointer fill-white/0 outline-none hover:fill-white/20 focus-visible:fill-white/30"
                      onClick={() => onPick({ x, depth, side })}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          onPick({ x, depth, side })
                        }
                      }}
                    />
                  )
                }),
              ),
            )}
      </Table>
    </svg>
  )
}

/** One small table per ball, like a coach's step-by-step sheet, captioned with its label and note. */
export function StepPanels({ steps }: { steps: PatternStep[] }) {
  const marker = useId().replace(/:/g, "")
  if (steps.length < 2) return null
  return (
    <ol aria-label="Step by step" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {steps.map((step, i) => (
        <li key={i} className="flex flex-col items-center gap-1 rounded-lg border bg-card p-2 text-center">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Step ${i + 1}: ${step.stroke}`} className="h-auto w-full max-w-[140px]">
            <ArrowHead id={`${marker}-${i}`} />
            <Table>
              <Arrow from={origin(steps, i)} to={point(step)} marker={`${marker}-${i}`} />
              <Ball step={step} n={i + 1} />
            </Table>
          </svg>
          <span className="text-sm font-semibold">
            {i + 1} · {step.stroke}
          </span>
          {step.note && <span className="text-xs text-muted-foreground">{step.note}</span>}
        </li>
      ))}
    </ol>
  )
}
