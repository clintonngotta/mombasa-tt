import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

// TASK-005 component gallery: tokens and control states at a glance.
const SWATCHES = [
  ["brand.navy", "bg-brand-navy"],
  ["brand.blue", "bg-brand-blue"],
  ["brand.gold", "bg-brand-gold"],
  ["brand.cyan", "bg-brand-cyan"],
  ["surface.canvas", "bg-background"],
  ["surface.selected", "bg-surface-selected"],
  ["status.success", "bg-success"],
  ["status.warning", "bg-warning"],
  ["status.danger", "bg-destructive"],
] as const

export function GalleryPage() {
  return (
    <div className="flex flex-col gap-8">
      <h1 className="text-3xl">Component gallery</h1>

      <section className="flex flex-col gap-3">
        <h2 className="text-2xl">Colour tokens</h2>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {SWATCHES.map(([name, cls]) => (
            <li key={name} className="flex items-center gap-3">
              <span className={`size-10 shrink-0 rounded-lg border ${cls}`} />
              <span className="text-sm">{name}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-2xl">Type</h2>
        <p className="font-display text-[32px] leading-9 font-bold">Heading 32/36</p>
        <p className="font-display text-2xl font-semibold">Heading 24/28</p>
        <p>Body 16/24 — Source Sans 3.</p>
        <p className="text-sm text-muted-foreground">Metadata 14/20</p>
        <p className="font-display text-8xl font-bold tabular">11 – 9</p>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-2xl">Controls</h2>
        <div className="flex flex-wrap gap-3">
          <Button>Primary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="destructive">Destructive</Button>
          <Button disabled>Disabled</Button>
        </div>
        <Card className="max-w-[640px]">
          <CardHeader>
            <CardTitle>Form card</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Label htmlFor="gallery-email">Email</Label>
            <Input id="gallery-email" type="email" placeholder="you@example.com" />
            <Input aria-invalid placeholder="Invalid state" />
          </CardContent>
        </Card>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-2xl">Scoring deck surface</h2>
        <div className="grid grid-cols-2 divide-x divide-white/20 rounded-2xl bg-brand-navy text-white">
          {["A. Mwangi", "K. Otieno"].map((name, i) => (
            <div key={name} className="flex flex-col items-center gap-2 p-4">
              <span className="text-center font-semibold">{name}</span>
              <span className="font-display text-8xl font-bold tabular">{i === 0 ? 7 : 5}</span>
              {i === 0 && (
                <span className="rounded-full bg-brand-gold px-3 py-1 text-sm font-semibold text-brand-navy">
                  Serving
                </span>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
