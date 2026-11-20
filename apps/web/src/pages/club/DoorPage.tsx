import { useState, type FormEvent } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BadgeCheck, Undo2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { AccessLost } from "@/components/clubs/AccessLost"
import { PlayerPicker, type Picked } from "@/components/tournaments/PlayerPicker"
import { ApiError, errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { formatMoney } from "@/lib/coaching"
import { formatDay } from "@/lib/dates"
import { activePassOf, doorKeys, listPrices, listVisits, METHOD_LABEL, recordVisit, reverseVisit, type DoorVisit, type Method } from "@/lib/door"
import { listVenues, venueKeys } from "@/lib/venues"
import { cn } from "@/lib/utils"

/**
 * The door screen of one branch (REQ-044): record who came, the pass sold, and what was collected and
 * how. Recording is not payment processing. A mistake is reversed with a reason and stays on the list.
 */
export function DoorPage() {
  const { id = "" } = useParams()
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "facilities.manage")
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId), enabled: allowed })
  const visits = useQuery({ queryKey: doorKeys.visits(orgId, id, ""), queryFn: () => listVisits(orgId, id, ""), enabled: allowed })
  const accessLost = useAdminAccessLost(venues.error, visits.error)
  const venue = venues.data?.find((v) => v.id === id)
  const today = visits.data?.[0]?.visited_on
  const kept = (visits.data ?? []).filter((v) => !v.reversed)
  const collected = kept.reduce((sum, v) => sum + v.amount_minor, 0)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={`/club/venues/${id}`}>{venue?.name ?? "Venue"}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Door</h1>
        {venue && <p className="text-muted-foreground">{venue.name}</p>}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {allowed && !accessLost && (
        <>
          <RecordVisit orgId={orgId} venueId={id} />
          <section aria-labelledby="today-heading" className="flex flex-col gap-3">
            <h2 id="today-heading" className="text-xl font-bold">
              Today{today ? `, ${formatDay(today)}` : ""}
            </h2>
            <p className="text-muted-foreground">
              {kept.length} {kept.length === 1 ? "visit" : "visits"} · {formatMoney(collected, kept[0]?.currency ?? "KES")} collected
            </p>
            {visits.isError && <FormAlert>{errorMessage(visits.error, "We couldn't load today's visits.")}</FormAlert>}
            <ul className="flex flex-col gap-2">
              {(visits.data ?? []).map((visit) => (
                <li key={visit.id}>
                  <VisitRow orgId={orgId} venueId={id} visit={visit} />
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}

function RecordVisit({ orgId, venueId }: { orgId: string; venueId: string }) {
  const queryClient = useQueryClient()
  const prices = useQuery({ queryKey: doorKeys.prices(orgId, venueId), queryFn: () => listPrices(orgId, venueId) })
  const [who, setWho] = useState<"player" | "walk_in">("walk_in")
  const [player, setPlayer] = useState<Picked[]>([])
  const [name, setName] = useState("")
  const [passId, setPassId] = useState("")
  const [method, setMethod] = useState<Method>("cash")
  const [reference, setReference] = useState("")
  const playerId = who === "player" ? player[0]?.id : undefined
  const held = useQuery({
    queryKey: doorKeys.activePass(orgId, venueId, playerId ?? ""),
    queryFn: () => activePassOf(orgId, venueId, playerId ?? ""),
    enabled: !!playerId,
  })
  const onPass = method === "pass"
  const offered = (prices.data ?? []).filter((p) => p.active)
  const save = useMutation({
    mutationFn: () =>
      recordVisit(orgId, venueId, {
        pass_id: onPass ? null : passId,
        player_id: playerId ?? null,
        walk_in_name: who === "walk_in" ? name.trim() : "",
        method,
        reference: method === "mpesa" || method === "other" ? reference.trim() : "",
      }),
    onSuccess: () => {
      setPlayer([])
      setName("")
      setReference("")
      setMethod("cash")
      void queryClient.invalidateQueries({ queryKey: doorKeys.all })
    },
  })
  const errors = save.error instanceof ApiError ? save.error.fieldErrors() : {}
  const ready = (who === "player" ? !!playerId : !!name.trim()) && (onPass || !!passId) && (method === "cash" || onPass || !!reference.trim())
  const methods = [
    { value: "cash" as Method, label: "Cash" },
    { value: "mpesa" as Method, label: "M-Pesa" },
    { value: "other" as Method, label: "Other" },
    ...(who === "player" && held.data ? [{ value: "pass" as Method, label: "On their pass" }] : []),
  ]
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">Record a visit</h2>
      <ChoiceGroup
        legend="Who"
        options={[
          { value: "walk_in", label: "Walk-in", description: "Name kept only for this facility" },
          { value: "player", label: "Coast TT player" },
        ]}
        value={who}
        onChange={(value) => {
          setWho(value)
          if (value === "walk_in" && method === "pass") setMethod("cash")
        }}
      />
      {who === "walk_in" ? (
        <Field label="Visitor's name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} error={errors.walk_in_name} />
      ) : (
        <PlayerPicker label="Player" picked={player} max={1} onChange={setPlayer} error={errors.player_id} />
      )}
      {who === "player" && held.data && (
        <p role="status" className="flex items-center gap-2 rounded-lg border border-success/40 bg-success/10 p-3 font-semibold">
          <BadgeCheck aria-hidden className="size-5 text-success" /> {held.data.pass_name} valid until {formatDay(held.data.valid_until)}
        </p>
      )}
      <ChoiceGroup legend="How they paid" options={methods} value={method} onChange={setMethod} columns={methods.length > 3 ? 2 : 3} />
      {!onPass && (
        <ChoiceGroup
          legend="What they paid for"
          options={offered.map((p) => ({ value: p.id, label: `${p.name} · ${formatMoney(p.amount_minor, p.currency ?? "KES")}` }))}
          value={passId}
          onChange={setPassId}
          error={errors.pass_id}
        />
      )}
      {prices.isSuccess && offered.length === 0 && <p className="text-muted-foreground">Add a price on the venue page first.</p>}
      {(method === "mpesa" || method === "other") && (
        <Field label={method === "mpesa" ? "M-Pesa reference" : "Payment reference"} maxLength={60} value={reference} onChange={(e) => setReference(e.target.value.toUpperCase())} error={errors.reference} />
      )}
      {save.isError && !Object.keys(errors).length && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      {save.isSuccess && (
        <p role="status" className="text-sm text-success">
          Recorded.
        </p>
      )}
      <Button type="submit" size="lg" className="self-start" disabled={!ready || save.isPending}>
        {save.isPending ? "Recording…" : "Record visit"}
      </Button>
    </form>
  )
}

function VisitRow({ orgId, venueId, visit }: { orgId: string; venueId: string; visit: DoorVisit }) {
  const queryClient = useQueryClient()
  const [reversing, setReversing] = useState(false)
  const [reason, setReason] = useState("")
  const undo = useMutation({
    mutationFn: () => reverseVisit(orgId, venueId, visit.id, reason.trim()),
    onSuccess: () => {
      setReversing(false)
      void queryClient.invalidateQueries({ queryKey: doorKeys.all })
    },
  })
  const time = new Date(visit.recorded_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
  return (
    <div className={cn(ROW, "flex-col items-stretch", visit.reversed && "opacity-70")}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className={cn("font-semibold", visit.reversed && "line-through")}>
            {visit.player_name ?? visit.walk_in_name} · {visit.pass_name}
          </span>
          <span className="text-sm text-muted-foreground">
            {time} · {visit.method === "pass" ? METHOD_LABEL.pass : `${formatMoney(visit.amount_minor, visit.currency)} ${METHOD_LABEL[visit.method]}`}
            {visit.reference && ` · ${visit.reference}`}
            {visit.recorded_by_name && ` · by ${visit.recorded_by_name}`}
          </span>
          {visit.reversed && <span className="text-sm font-semibold">Reversed: {visit.reversal_reason}</span>}
        </span>
        {!visit.reversed && !reversing && (
          <Button variant="ghost" onClick={() => setReversing(true)}>
            <Undo2 aria-hidden className="size-4" /> Reverse
          </Button>
        )}
      </div>
      {reversing && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Why reverse it" className="min-w-48 flex-1" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button variant="destructive" disabled={!reason.trim() || undo.isPending} onClick={() => undo.mutate()}>
            Reverse visit
          </Button>
          <Button variant="ghost" onClick={() => setReversing(false)}>
            Keep it
          </Button>
        </div>
      )}
      {undo.isError && <FormAlert>{errorMessage(undo.error)}</FormAlert>}
    </div>
  )
}
