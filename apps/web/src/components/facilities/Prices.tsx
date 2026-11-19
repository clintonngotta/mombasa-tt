import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { DoorOpen } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { TextAreaField } from "@/components/forms/SelectField"
import { ApiError, errorMessage } from "@/lib/api"
import { formatMoney } from "@/lib/coaching"
import { ROW } from "@/lib/clubAdmin"
import { createPrice, doorKeys, KIND_LABEL, listPrices, updatePrice, type Price } from "@/lib/door"
import type { Venue } from "@/lib/venues"

const KINDS = (Object.keys(KIND_LABEL) as Price["kind"][]).map((value) => ({ value, label: KIND_LABEL[value] }))

/** A branch's prices (REQ-044): a day pass and longer passes, in KES with what each includes. */
export function Prices({ orgId, venue }: { orgId: string; venue: Venue }) {
  const queryClient = useQueryClient()
  const prices = useQuery({ queryKey: doorKeys.prices(orgId, venue.id), queryFn: () => listPrices(orgId, venue.id) })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: doorKeys.prices(orgId, venue.id) })
    void queryClient.invalidateQueries({ queryKey: ["facilities"] })
  }
  const toggle = useMutation({ mutationFn: (price: Price) => updatePrice(orgId, venue.id, price.id, { active: !price.active }), onSuccess: refresh })

  return (
    <section aria-labelledby="prices-heading" className="flex flex-col gap-3 border-t pt-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="prices-heading" className="text-2xl font-bold">
          Prices
        </h2>
        <Link to={`/club/venues/${venue.id}/door`} className={buttonVariants({ variant: "default" })}>
          <DoorOpen aria-hidden className="size-5" /> Door screen
        </Link>
      </div>
      <p className="text-sm text-muted-foreground">What visitors pay at the door. Recording a payment here never charges anyone: you collect it yourself.</p>
      {prices.isError && <FormAlert>{errorMessage(prices.error, "We couldn't load the prices.")}</FormAlert>}
      {toggle.isError && <FormAlert>{errorMessage(toggle.error)}</FormAlert>}
      <ul className="flex flex-col gap-2">
        {(prices.data ?? []).map((price) => (
          <li key={price.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">
                {price.name} · {formatMoney(price.amount_minor, price.currency ?? "KES")}
              </span>
              <span className="text-sm text-muted-foreground">
                {KIND_LABEL[price.kind]}
                {price.kind === "sessions" && ` · ${price.sessions} visits within ${price.valid_days} days`}
                {!price.active && " · not offered"}
              </span>
              {price.benefits && price.benefits.length > 0 && <span className="text-sm">{price.benefits.join(" · ")}</span>}
            </span>
            <Button variant="outline" disabled={toggle.isPending && toggle.variables?.id === price.id} onClick={() => toggle.mutate(price)}>
              {price.active ? "Stop offering" : "Offer again"}
            </Button>
          </li>
        ))}
      </ul>
      <NewPrice orgId={orgId} venueId={venue.id} onSaved={refresh} />
    </section>
  )
}

function NewPrice({ orgId, venueId, onSaved }: { orgId: string; venueId: string; onSaved: () => void }) {
  const [name, setName] = useState("")
  const [kind, setKind] = useState<Price["kind"]>("day")
  const [amount, setAmount] = useState("")
  const [sessions, setSessions] = useState("")
  const [days, setDays] = useState("")
  const [benefits, setBenefits] = useState("")
  const save = useMutation({
    mutationFn: () =>
      createPrice(orgId, venueId, {
        name: name.trim() || KIND_LABEL[kind],
        kind,
        amount_minor: Math.round(Number(amount) * 100),
        currency: "KES",
        sessions: kind === "sessions" ? Number(sessions) || null : null,
        valid_days: kind === "sessions" ? Number(days) || null : null,
        benefits: benefits
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      setName("")
      setAmount("")
      setSessions("")
      setDays("")
      setBenefits("")
      onSaved()
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h3 className="text-lg font-bold">Add a price</h3>
      <ChoiceGroup legend="Kind" options={KINDS} value={kind} onChange={setKind} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" optional maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder={KIND_LABEL[kind]} error={errors.name} />
        <Field label="Price (KES)" type="number" min={0} step="0.01" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="200" error={errors.amount_minor} />
      </div>
      {kind === "sessions" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Visits included" type="number" min={2} max={100} inputMode="numeric" value={sessions} onChange={(e) => setSessions(e.target.value)} error={errors.sessions} />
          <Field label="Valid for (days)" type="number" min={1} max={366} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} error={errors.valid_days} />
        </div>
      )}
      <TextAreaField label="What it includes" optional rows={3} value={benefits} onChange={(e) => setBenefits(e.target.value)} hint="One per line, for example Table time, Ball hire." error={errors.benefits} />
      {save.isError && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Button type="submit" className="self-start" disabled={save.isPending || amount === "" || Number(amount) < 0}>
        {save.isPending ? "Saving…" : "Add price"}
      </Button>
    </form>
  )
}
