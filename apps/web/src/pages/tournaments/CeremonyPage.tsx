import { useState, type FormEvent } from "react"
import { NewAward } from "@/components/tournaments/AwardForm"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Check, Medal, Sparkles, Trash2, Trophy } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import {
  ceremonyKeys,
  deleteAward,
  generateAwards,
  getCeremony,
  PLACE_MEDAL,
  presentAward,
  publishCeremony,
  reorderAwards,
  saveCeremony,
  type Award,
  type Ceremony,
} from "@/lib/ceremony"
import { useMemberships } from "@/lib/clubs"
import { formatInstant, fromZonedInput, toZonedInput } from "@/lib/dates"
import { canManageTournament, getTournament, tournamentKeys, type Tournament } from "@/lib/tournaments"
import { cn } from "@/lib/utils"

/** A tournament's award ceremony (REQ-049): staff plan it, order the awards, publish it and present each
 * award on the day; everyone else sees the published running order. */
export function CeremonyPage() {
  const { id = "" } = useParams()
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const ceremony = useQuery({
    queryKey: ceremonyKeys.detail(id),
    queryFn: () => getCeremony(id).catch((error) => (error instanceof ApiError && error.status === 404 ? null : Promise.reject(error))),
  })
  const t = tournament.data
  const staff = !!t && canManageTournament(memberships, t)

  return (
    <div className="flex max-w-[760px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <h1 className="flex items-center gap-2 text-[32px] leading-9 font-bold">
        <Trophy aria-hidden className="size-8 text-brand-gold" /> Award ceremony
      </h1>
      {(tournament.isError || ceremony.isError) && <FormAlert>{errorMessage(tournament.error ?? ceremony.error)}</FormAlert>}
      {ceremony.isSuccess && !ceremony.data && !staff && <p className="text-muted-foreground">The organizers haven't published the ceremony yet.</p>}
      {t && ceremony.isSuccess && staff && <Plan tournament={t} ceremony={ceremony.data} />}
      {t && ceremony.data && !staff && <RunningOrder tournament={t} ceremony={ceremony.data} />}
    </div>
  )
}

function useSet(tournamentId: string) {
  const queryClient = useQueryClient()
  return (fresh: Ceremony) => {
    queryClient.setQueryData(ceremonyKeys.detail(tournamentId), fresh)
    return queryClient.invalidateQueries({ queryKey: ceremonyKeys.honours })
  }
}

function Details({ tournament: t, ceremony }: { tournament: Tournament; ceremony: Ceremony | null }) {
  const set = useSet(t.id)
  const [startsAt, setStartsAt] = useState(toZonedInput(ceremony?.starts_at ?? null, t.timezone))
  const [location, setLocation] = useState(ceremony?.location ?? "")
  const [host, setHost] = useState(ceremony?.host ?? "")
  const save = useMutation({
    mutationFn: () => saveCeremony(t.id, { starts_at: startsAt ? fromZonedInput(startsAt, t.timezone) : null, location: location.trim(), host: host.trim() }),
    onSuccess: set,
  })
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <h2 className="text-xl font-bold">When and where</h2>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Starts" optional type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
        <Field label="Where" optional maxLength={200} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Main hall" />
        <Field label="Master of ceremonies" optional maxLength={120} value={host} onChange={(e) => setHost(e.target.value)} />
      </div>
      <Button type="submit" variant="outline" className="self-start" disabled={save.isPending}>
        {save.isSuccess ? "Saved" : "Save"}
      </Button>
    </form>
  )
}

function Plan({ tournament: t, ceremony }: { tournament: Tournament; ceremony: Ceremony | null }) {
  const set = useSet(t.id)
  const generate = useMutation({ mutationFn: () => generateAwards(t.id), onSuccess: set })
  const publish = useMutation({ mutationFn: () => publishCeremony(t.id), onSuccess: set })
  const reorder = useMutation({ mutationFn: (ids: string[]) => reorderAwards(t.id, ids), onSuccess: set })
  const remove = useMutation({ mutationFn: (awardId: string) => deleteAward(t.id, awardId), onSuccess: set })
  const present = useMutation({ mutationFn: (awardId: string) => presentAward(t.id, awardId), onSuccess: set })
  const awards = ceremony?.awards ?? []
  const draft = !ceremony || ceremony.status === "draft"
  const error = generate.error ?? publish.error ?? reorder.error ?? remove.error ?? present.error
  const closed = t.status === "draft" || t.status === "cancelled"
  const move = (index: number, by: number) => {
    const ids = awards.map((a) => a.id)
    ;[ids[index], ids[index + by]] = [ids[index + by], ids[index]]
    reorder.mutate(ids)
  }
  const next = awards.find((a) => !a.presented_at)

  if (closed) return <FormAlert>Publish the tournament before planning its ceremony.</FormAlert>
  return (
    <>
      <Details key={ceremony?.id ?? "new"} tournament={t} ceremony={ceremony} />
      {error && <FormAlert>{errorMessage(error)}</FormAlert>}

      <section aria-labelledby="awards-heading" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="awards-heading" className="text-xl font-bold">
            Awards in order {ceremony && <span className="text-base font-normal text-muted-foreground">· {ceremony.status === "draft" ? "Draft" : ceremony.status === "done" ? "All presented" : "Published"}</span>}
          </h2>
          <Button variant="outline" disabled={generate.isPending} onClick={() => generate.mutate()}>
            <Sparkles aria-hidden className="size-4" /> {awards.some((a) => a.kind === "placement") ? "Update from results" : "Add placings from results"}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          Placings come from completed events: third place first and the winner last, with the first event of the programme at the end. Move awards to
          change the order.
        </p>
        {awards.length === 0 && <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">No awards yet. Add the placings once events are completed, or add an award of your own.</p>}
        <ol className="flex flex-col gap-2">
          {awards.map((award, index) => (
            <li key={award.id} className={cn("flex flex-wrap items-center gap-3 rounded-xl border bg-card p-3", award === next && !draft && "border-brand-blue ring-2 ring-brand-blue/30", award.presented_at && "opacity-70")}>
              <span className="w-6 text-center font-bold tabular-nums text-muted-foreground">{index + 1}</span>
              <AwardLine award={award} />
              <div className="flex gap-1">
                <Button variant="ghost" size="icon" aria-label={`Move ${award.title} up`} disabled={index === 0 || reorder.isPending} onClick={() => move(index, -1)}>
                  <ArrowUp aria-hidden className="size-5" />
                </Button>
                <Button variant="ghost" size="icon" aria-label={`Move ${award.title} down`} disabled={index === awards.length - 1 || reorder.isPending} onClick={() => move(index, 1)}>
                  <ArrowDown aria-hidden className="size-5" />
                </Button>
                {!award.presented_at && (
                  <Button variant="ghost" size="icon" aria-label={`Remove ${award.title}`} disabled={remove.isPending} onClick={() => remove.mutate(award.id)}>
                    <Trash2 aria-hidden className="size-5" />
                  </Button>
                )}
                {!draft && (
                  <Button variant={award.presented_at ? "outline" : "default"} disabled={present.isPending} onClick={() => present.mutate(award.id)}>
                    {award.presented_at ? (
                      <>
                        <Check aria-hidden className="size-4" /> Presented
                      </>
                    ) : (
                      "Present"
                    )}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ol>
        <NewAward tournamentId={t.id} />
      </section>

      {draft && awards.length > 0 && (
        <section className="flex flex-col gap-2 border-t pt-6">
          <p className="text-muted-foreground">Publishing shows the running order to everyone who sees the tournament, and puts each award on its winner's profile.</p>
          <Button size="lg" className="self-start" disabled={publish.isPending} onClick={() => publish.mutate()}>
            Publish the ceremony
          </Button>
        </section>
      )}
    </>
  )
}

function AwardLine({ award }: { award: Award }) {
  return (
    <span className="flex min-w-0 flex-1 items-start gap-2">
      {award.place ? (
        <Medal aria-label={`${PLACE_MEDAL[award.place]} medal`} className={cn("mt-0.5 size-5 shrink-0", award.place === 1 ? "text-brand-gold" : award.place === 2 ? "text-slate-400" : "text-amber-700")} />
      ) : (
        <Trophy aria-hidden className="mt-0.5 size-5 shrink-0 text-brand-blue" />
      )}
      <span className="flex min-w-0 flex-col">
        <span className="font-semibold">{award.title}</span>
        <span>{award.receives || <span className="text-muted-foreground">Recipient to be named</span>}</span>
        {(award.prize || award.presenter) && (
          <span className="text-sm text-muted-foreground">
            {[award.prize, award.presenter && `presented by ${award.presenter}`].filter(Boolean).join(" · ")}
          </span>
        )}
      </span>
    </span>
  )
}

function RunningOrder({ tournament: t, ceremony }: { tournament: Tournament; ceremony: Ceremony }) {
  return (
    <section aria-label="Running order" className="flex flex-col gap-3">
      <p className="text-muted-foreground">
        {[ceremony.starts_at && formatInstant(ceremony.starts_at, t.timezone), ceremony.location, ceremony.host && `hosted by ${ceremony.host}`].filter(Boolean).join(" · ")}
      </p>
      <ol className="flex flex-col gap-2">
        {ceremony.awards.map((award, index) => (
          <li key={award.id} className="flex items-center gap-3 rounded-xl border bg-card p-3">
            <span className="w-6 text-center font-bold tabular-nums text-muted-foreground">{index + 1}</span>
            <AwardLine award={award} />
            {award.presented_at && <Check aria-label="Presented" className="size-5 text-success" />}
          </li>
        ))}
      </ol>
      <Link to={`/tournaments/${t.id}`} className={cn(buttonVariants({ variant: "outline" }), "self-start")}>
        Back to the tournament
      </Link>
    </section>
  )
}
