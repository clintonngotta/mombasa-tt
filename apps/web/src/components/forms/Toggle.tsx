import { useId, type ReactNode } from "react"

/** A labelled on/off switch backed by a native checkbox, with a description underneath. */
export function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  description: ReactNode
}) {
  const descriptionId = useId()
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-xl border bg-card p-4 has-focus-visible:ring-3 has-focus-visible:ring-ring/50">
      <input
        type="checkbox"
        role="switch"
        aria-describedby={descriptionId}
        checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only"
      />
      <span
        aria-hidden
        className="mt-0.5 flex h-7 w-12 shrink-0 items-center rounded-full bg-border p-0.5 transition-colors motion-reduce:transition-none peer-checked:bg-brand-blue peer-checked:[&>span]:translate-x-5"
      >
        <span className="size-6 rounded-full bg-white shadow transition-transform motion-reduce:transition-none" />
      </span>
      <span className="flex flex-col">
        <span className="font-semibold">{label}</span>
        <span id={descriptionId} className="text-sm text-muted-foreground">
          {description}
        </span>
      </span>
    </label>
  )
}
