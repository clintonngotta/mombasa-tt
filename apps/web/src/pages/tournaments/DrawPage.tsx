import { useState } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, X } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { DrawView } from "@/components/tournaments/DrawView"
import { EventStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { formatInstant } from "@/lib/dates"
import { drawKeys, getDraw, previewDraw, publishDraw, type EventDraw } from "@/lib/draws"
import { entryKeys, entryTitle, listEntries, type Entry } from "@/lib/entries"
import { canManageTournament, eventSummary, getTournament, isClosed, SEEDING_LABEL, tournamentKeys, type Tournament, type TournamentEvent } from "@/lib/tournaments"

/** The draw of one event (REQ-009): the published draw for everyone, and the organizers' draw desk. */
export function DrawPage() {
  const { id = "", eventId = "" } = useParams()
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const draw = useQuery({ queryKey: drawKeys.event(eventId), queryFn: () => getDraw(id, eventId), enabled: tournament.isSuccess })
  const t = tournament.data
  const event = t?.events.find((candidate) => candidate.id === eventId)
  const staff = !!t && canManageTournament(memberships, t)
  const missing = (tournament.error instanceof ApiError && tournament.error.status === 404) || (!!t && !event)
  const published = draw.data?.published

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      {tournament.isPending && <p className="text-muted-foreground">Loading event…</p>}
      {missing && <FormAlert>This event doesn't exist or hasn't been published.</FormAlert>}
      {tournament.isError && !missing && <FormAlert>{errorMessage(tournament.error, "We couldn't load this event.")}</FormAlert>}
      {t && event && (
        <>
          <header className="flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <h1 className="min-w-0 text-[32px] leading-9 font-bold break-words">{event.name}: draw</h1>
              <EventStatusChip status={event.status} />
            </div>
            <p className="text-muted-foreground">{eventSummary(event)}</p>
          </header>
          {draw.isPending && <p className="text-muted-foreground">Loading draw…</p>}
          {draw.isError && <FormAlert>{errorMessage(draw.error, "We couldn't load the draw.")}</FormAlert>}
          {draw.data && (
            <>
              {staff && <Desk tournament={t} event={event} draw={draw.data} />}
              <section aria-labelledby="draw-heading" className="flex flex-col gap-4">
                <h2 id="draw-heading" className="text-2xl font-bold">
                  {published ? `Published draw (version ${published.version})` : "Draw"}
                </h2>
                {published ? (
                  <>
                    <p className="text-sm text-muted-foreground">Published {published.published_at && formatInstant(published.published_at, t.timezone)}.</p>
                    {published.stale && <FormAlert>The entries have changed since this draw was published. The organizers will publish a new one.</FormAlert>}
                    <DrawView draw={published} />
                  </>
                ) : (
                  <p className="text-muted-foreground">The draw hasn't been published yet.</p>
                )}
              </section>
            </>
          )}
        </>
      )}
    </div>
  )
}

/** Seeds in order, a preview that can be drawn again, and publication. */
function Desk({ tournament: t, event, draw }: { tournament: Tournament; event: TournamentEvent; draw: EventDraw }) {
  const queryClient = useQueryClient()
  const [seeds, setSeeds] = useState<string[]>([])
  const open = t.status !== "draft" && !isClosed(t) && event.status === "scheduled"
  const seeded = event.seeding !== "none"
  const entries = useQuery({ queryKey: entryKeys.event(event.id), queryFn: () => listEntries(t.id, event.id), enabled: open })
  const accepted = (entries.data?.results ?? []).filter((entry) => entry.status === "accepted")
  const byId = new Map(accepted.map((entry) => [entry.id, entry]))
  const chosen = seeds.filter((id) => byId.has(id)) // an entry withdrawn since is no longer a seed
  const settle = (fresh: EventDraw) => queryClient.setQueryData(drawKeys.event(event.id), fresh)
  const make = useMutation({ mutationFn: () => previewDraw(t.id, event.id, seeded ? chosen : []), onSuccess: settle })
  const publish = useMutation({ mutationFn: () => publishDraw(t.id, event.id), onSuccess: settle })
  const preview = draw.preview

  function move(index: number, by: number) {
    const next = [...chosen]
    const [entry] = next.splice(index, 1)
    next.splice(index + by, 0, entry)
    setSeeds(next)
  }

  return (
    <section aria-labelledby="draw-desk-heading" className="flex flex-col gap-4 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <div className="flex flex-col gap-1">
        <h2 id="draw-desk-heading" className="text-2xl font-bold">
          Draw desk
        </h2>
        <p className="text-sm text-muted-foreground">Only people who run competitions for {t.organization.name} see this.</p>
      </div>
      {!open ? (
        <p className="text-muted-foreground">{t.status === "draft" ? "Publish the tournament before making a draw." : "The event has started, so its draw is fixed."}</p>
      ) : (
        <>
          <p>
            {accepted.length} accepted {accepted.length === 1 ? "entry" : "entries"} will be drawn. {SEEDING_LABEL[event.seeding]}.
          </p>
          {entries.isError && <FormAlert>{errorMessage(entries.error, "We couldn't load the entries.")}</FormAlert>}
          {seeded && (
            <div className="flex flex-col gap-3 rounded-lg border bg-card p-3">
              <h3 className="text-lg font-bold">Seeds</h3>
              <p className="text-sm text-muted-foreground">
                Put the seeds in order, best first. {event.seeding === "rating" && "Ratings aren't calculated yet, so the order is yours to give. "}
                Everyone else is drawn by lot.
              </p>
              {chosen.length > 0 && (
                <ol className="flex flex-col gap-2" aria-label="Seeds in order">
                  {chosen.map((id, index) => {
                    const title = entryTitle(byId.get(id) as Entry)
                    return (
                      <li key={id} className="flex min-h-12 items-center gap-1 rounded-lg border pl-3">
                        <span className="w-6 font-semibold tabular-nums">{index + 1}</span>
                        <span className="min-w-0 flex-1 break-words">{title}</span>
                        <Button variant="ghost" size="icon" aria-label={`Move ${title} up`} disabled={index === 0} onClick={() => move(index, -1)}>
                          <ArrowUp aria-hidden className="size-5" />
                        </Button>
                        <Button variant="ghost" size="icon" aria-label={`Move ${title} down`} disabled={index === chosen.length - 1} onClick={() => move(index, 1)}>
                          <ArrowDown aria-hidden className="size-5" />
                        </Button>
                        <Button variant="ghost" size="icon" aria-label={`Unseed ${title}`} onClick={() => setSeeds(chosen.filter((seed) => seed !== id))}>
                          <X aria-hidden className="size-5" />
                        </Button>
                      </li>
                    )
                  })}
                </ol>
              )}
              <ul className="flex flex-wrap gap-2" aria-label="Unseeded entries">
                {accepted
                  .filter((entry) => !chosen.includes(entry.id))
                  .map((entry) => (
                    <li key={entry.id}>
                      <Button variant="outline" aria-label={`Seed ${entryTitle(entry)} next`} onClick={() => setSeeds([...chosen, entry.id])}>
                        {entryTitle(entry)}
                      </Button>
                    </li>
                  ))}
              </ul>
            </div>
          )}
          {make.isError && <FormAlert>{errorMessage(make.error)}</FormAlert>}
          <Button size="lg" variant={preview ? "outline" : "default"} className="self-start" disabled={make.isPending} onClick={() => make.mutate()}>
            {make.isPending ? "Drawing…" : preview ? "Draw again" : "Make the draw"}
          </Button>

          {preview && (
            <div className="flex flex-col gap-4 rounded-lg border bg-card p-3">
              <div className="flex flex-col gap-1">
                <h3 className="text-lg font-bold">Preview (version {preview.version})</h3>
                <p className="text-sm text-muted-foreground">Nobody else sees this until you publish it.</p>
              </div>
              {preview.stale && <FormAlert>The accepted entries changed since this was drawn. Draw again before publishing.</FormAlert>}
              <DrawView draw={preview} />
              {publish.isError && <FormAlert>{errorMessage(publish.error)}</FormAlert>}
              <Button size="lg" className="self-start" disabled={publish.isPending || preview.stale} onClick={() => publish.mutate()}>
                {publish.isPending ? "Publishing…" : draw.published ? "Publish as the new draw" : "Publish draw"}
              </Button>
              {draw.published && <p className="text-sm text-muted-foreground">Version {draw.published.version} stays on record as superseded.</p>}
            </div>
          )}
        </>
      )}
    </section>
  )
}
