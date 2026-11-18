import { cn } from "@/lib/utils"

/** Latest rated matches, newest first, as letters with their meaning spoken: never colour alone (REQ-002). */
export function Form({ form }: { form: readonly ("W" | "L")[] }) {
  if (form.length === 0) return <span className="text-sm text-muted-foreground">No rated matches yet</span>
  return (
    <span className="flex gap-1" role="img" aria-label={`Latest results, newest first: ${form.map((letter) => (letter === "W" ? "won" : "lost")).join(", ")}`}>
      {form.map((letter, index) => (
        <span key={index} aria-hidden className={cn("flex size-6 items-center justify-center rounded text-xs font-bold", letter === "W" ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive")}>
          {letter}
        </span>
      ))}
    </span>
  )
}
