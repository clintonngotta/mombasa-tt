import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Flag, MonitorPlay, SquareArrowOutUpRight, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import {
  REPORT_REASONS,
  addStream,
  listStreams,
  removeStream,
  reportStream,
  streamKeys,
  streamUrlProblem,
  type LiveStream,
  type StreamReportReason,
} from "@/lib/streams"
import type { Tournament } from "@/lib/tournaments"

type Props = {
  tournament: Tournament
  staff: boolean
  /** On a match's page: that match's links first, then the whole tournament's. */
  matchId?: string
  /** Whether what the links show is happening now (shows the Live badge). */
  live: boolean
}

/** Where to watch a tournament or a match on YouTube, Facebook, TikTok and the like (REQ-042). Links open in a
 * new tab with their site shown; anyone can report one, and the host's staff add and remove them. */
export function WatchLinks({ tournament: t, staff, matchId, live }: Props) {
  const streams = useQuery({ queryKey: streamKeys.of(t.id, matchId), queryFn: () => listStreams(t.id, matchId) })
  const canAdd = staff && t.status !== "draft" && t.status !== "cancelled"
  const all = streams.data ?? []
  if (!canAdd && all.length === 0) return null

  const forMatch = all.filter((s) => s.match_id && s.match_id === matchId)
  const whole = all.filter((s) => !s.match_id)
  const onMatches = matchId ? [] : all.filter((s) => s.match_id)
  const headingId = matchId ? "watch-match-heading" : "watch-heading"

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="flex items-center gap-2 text-xl font-bold">
        <MonitorPlay aria-hidden className="size-5 text-brand-blue" />
        {live ? "Watch live" : "Watch"}
        {live && all.length > 0 && <span className="rounded-full bg-destructive px-2 py-0.5 text-xs font-bold tracking-wide text-white uppercase">Live</span>}
      </h2>
      {streams.isError && <FormAlert>{errorMessage(streams.error, "We couldn't load the watch links.")}</FormAlert>}
      {matchId && forMatch.length > 0 && <Links tournamentId={t.id} streams={forMatch} staff={staff} />}
      {whole.length > 0 && (
        <>
          {matchId && forMatch.length > 0 && <h3 className="font-semibold">Whole tournament</h3>}
          <Links tournamentId={t.id} streams={whole} staff={staff} />
        </>
      )}
      {onMatches.length > 0 && (
        <>
          <h3 className="font-semibold">Matches being streamed</h3>
          <Links tournamentId={t.id} streams={onMatches} staff={staff} showMatch />
        </>
      )}
      {canAdd && <AddLink tournamentId={t.id} matchId={matchId} />}
    </section>
  )
}

function Links({ tournamentId, streams, staff, showMatch = false }: { tournamentId: string; streams: LiveStream[]; staff: boolean; showMatch?: boolean }) {
  return (
    <ul className="flex flex-col gap-2">
      {streams.map((stream) => (
        <StreamRow key={stream.id} tournamentId={tournamentId} stream={stream} staff={staff} showMatch={showMatch} />
      ))}
    </ul>
  )
}

function StreamRow({ tournamentId, stream, staff, showMatch }: { tournamentId: string; stream: LiveStream; staff: boolean; showMatch: boolean }) {
  const queryClient = useQueryClient()
  const [reporting, setReporting] = useState(false)
  const [reason, setReason] = useState<StreamReportReason>("broken")
  const remove = useMutation({
    mutationFn: () => removeStream(tournamentId, stream.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: streamKeys.all }),
  })
  const report = useMutation({
    mutationFn: () => reportStream(tournamentId, stream.id, { reason }),
    onSuccess: () => setReporting(false),
  })
  const name = stream.title || stream.platform_label

  return (
    <li className={`${ROW} gap-y-2`}>
      <a
        href={stream.url}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="flex min-w-0 flex-1 items-center gap-3 rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-semibold break-words">{name}</span>
          <span className="text-sm text-muted-foreground">
            {stream.platform_label} · {stream.domain}
            <span className="sr-only"> (opens in a new tab)</span>
          </span>
        </span>
        <SquareArrowOutUpRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      </a>
      {staff ? (
        <>
          {!!stream.report_count && (
            <span className="flex items-center gap-1 text-sm font-semibold text-warning">
              <Flag aria-hidden className="size-4" /> {stream.report_count} {stream.report_count === 1 ? "report" : "reports"}
            </span>
          )}
          <Button variant="outline" size="sm" aria-label={`Remove ${name}`} disabled={remove.isPending} onClick={() => remove.mutate()}>
            <Trash2 aria-hidden className="size-4" /> Remove
          </Button>
        </>
      ) : report.isSuccess ? (
        <span className="text-sm text-muted-foreground">Reported. Thanks.</span>
      ) : (
        <Button variant="ghost" size="sm" aria-label={`Report ${name}`} aria-expanded={reporting} onClick={() => setReporting(!reporting)}>
          <Flag aria-hidden className="size-4" /> Report
        </Button>
      )}
      {showMatch && stream.match_label && stream.event_id && (
        <Link to={`/tournaments/${tournamentId}/events/${stream.event_id}/matches/${stream.match_id}`} className="basis-full text-sm text-brand-blue underline-offset-4 hover:underline">
          {stream.match_label}
        </Link>
      )}
      {reporting && !report.isSuccess && (
        <div className="flex basis-full flex-wrap items-end gap-2">
          <SelectField label="What's wrong?" options={REPORT_REASONS} value={reason} onChange={(value) => setReason(value as StreamReportReason)} />
          <Button disabled={report.isPending} onClick={() => report.mutate()}>
            {report.isPending ? "Sending…" : "Send report"}
          </Button>
        </div>
      )}
      {(remove.isError || report.isError) && (
        <div className="basis-full">
          <FormAlert>{errorMessage(remove.error ?? report.error)}</FormAlert>
        </div>
      )}
    </li>
  )
}

function AddLink({ tournamentId, matchId }: { tournamentId: string; matchId?: string }) {
  const queryClient = useQueryClient()
  const [url, setUrl] = useState("")
  const [title, setTitle] = useState("")
  const [problem, setProblem] = useState<string | null>(null)
  const add = useMutation({
    mutationFn: () => addStream(tournamentId, { url: url.trim(), title: title.trim(), match_id: matchId ?? null }),
    onSuccess: () => {
      setUrl("")
      setTitle("")
      void queryClient.invalidateQueries({ queryKey: streamKeys.all })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const found = streamUrlProblem(url)
    setProblem(found)
    if (!found) add.mutate()
  }
  const serverProblem = add.error ? errorMessage(add.error, "We couldn't add that link.") : null

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-3 rounded-xl border border-dashed p-4">
      <p className="font-semibold">{matchId ? "Add a link to watch this match" : "Add a link to watch the tournament"}</p>
      <Field
        label="Link"
        type="url"
        inputMode="url"
        placeholder="https://www.youtube.com/live/…"
        hint="YouTube, Facebook, Instagram, TikTok, Twitch, X, Kick or any https site."
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        error={problem ?? undefined}
        required
      />
      <Field label="Name" optional maxLength={80} placeholder="e.g. Centre court, Club page" value={title} onChange={(event) => setTitle(event.target.value)} />
      {serverProblem && <FormAlert>{serverProblem}</FormAlert>}
      <Button type="submit" className="self-start" disabled={add.isPending}>
        {add.isPending ? "Adding…" : "Add link"}
      </Button>
    </form>
  )
}
