import { useState, type FormEvent } from "react"
import { useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Megaphone, Send, Sparkles, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { AwardsPanel } from "@/components/tournaments/AwardForm"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import {
  amendAnnouncement,
  announcementCardUrl,
  announcementPdfUrl,
  announcementKeys,
  deleteAnnouncement,
  editAnnouncement,
  generateAnnouncement,
  getAnnouncements,
  publishAnnouncement,
  SCOPE_LABEL,
  type Announcement,
  type AnnouncementScope,
  type GenerateBody,
} from "@/lib/announcements"
import { useMemberships } from "@/lib/clubs"
import { formatInstant } from "@/lib/dates"
import { getSchedule, scheduleKeys } from "@/lib/schedule"
import { canManageTournament, getTournament, tournamentKeys, type Tournament } from "@/lib/tournaments"

const SCOPES = Object.keys(SCOPE_LABEL) as AnnouncementScope[]

/** Results announcements (REQ-043): the organizers draft one from the official results, edit it, preview it as
 * text and as an image card, and publish it to the tournament's news feed. */
export function AnnouncementsPage() {
  const { id = "" } = useParams()
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const feed = useQuery({ queryKey: announcementKeys.feed(id), queryFn: () => getAnnouncements(id) })
  const t = tournament.data
  const staff = !!t && canManageTournament(memberships, t)
  const posts = feed.data?.results ?? []
  const drafts = posts.filter((post) => post.status === "draft")
  const published = posts.filter((post) => post.status === "published")
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <h1 className="flex items-center gap-2 text-[32px] leading-9 font-bold">
        <Megaphone aria-hidden className="size-7" /> Results announcements
      </h1>
      {(tournament.error || feed.error) && <FormAlert>{errorMessage(tournament.error ?? feed.error, "We couldn't load the announcements.")}</FormAlert>}
      {t && !staff && <FormAlert>Only the organizers write results announcements.</FormAlert>}
      {t && staff && (
        <>
          <p className="text-muted-foreground">
            A draft lists the official results only, with walkovers, retirements and disqualifications marked and the matches still to play as pending. Edit it as you like before publishing: a
            published post can't change, but after a correction you can publish an amendment beside it.
          </p>
          <AwardsPanel tournamentId={id} />
          <Generate tournament={t} />
          {drafts.map((post) => (
            <Draft key={post.id} post={post} tournamentId={id} />
          ))}
          {published.length > 0 && (
            <section aria-labelledby="published-heading" className="flex flex-col gap-3">
              <h2 id="published-heading" className="text-2xl font-bold">
                Published
              </h2>
              {published.map((post) => (
                <PublishedRow key={post.id} post={post} tournamentId={id} timeZone={t.timezone} />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  )
}

function useRefresh(tournamentId: string) {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: announcementKeys.feed(tournamentId) })
}

function Generate({ tournament: t }: { tournament: Tournament }) {
  const refresh = useRefresh(t.id)
  const [scope, setScope] = useState<AnnouncementScope>("round")
  const [eventId, setEventId] = useState(t.events[0]?.id ?? "")
  const [stage, setStage] = useState<"knockout" | "group">("knockout")
  const [round, setRound] = useState("1")
  const [day, setDay] = useState(t.starts_on)
  const [sessionId, setSessionId] = useState("")
  const schedule = useQuery({ queryKey: scheduleKeys.detail(t.id), queryFn: () => getSchedule(t.id), enabled: scope === "session" })
  const sessions = schedule.data?.sessions ?? []
  const make = useMutation({
    mutationFn: (body: GenerateBody) => generateAnnouncement(t.id, body),
    onSuccess: () => void refresh(),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const body: GenerateBody = { scope }
    if (scope === "event" || scope === "round") body.event_id = eventId
    if (scope === "round") Object.assign(body, { stage, round: Number(round) })
    if (scope === "day") body.day = day
    if (scope === "session") body.session_id = sessionId
    make.mutate(body)
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-xl font-bold">Draft from the official results</h2>
      <SelectField label="Results of" options={SCOPES.map((value) => ({ value, label: SCOPE_LABEL[value] }))} value={scope} onChange={(value) => setScope(value as AnnouncementScope)} />
      {(scope === "event" || scope === "round") && (
        <SelectField label="Event" options={t.events.map((event) => ({ value: event.id, label: event.name }))} value={eventId} onChange={setEventId} />
      )}
      {scope === "round" && (
        <div className="grid grid-cols-2 gap-3">
          <SelectField label="Stage" options={[{ value: "knockout", label: "Knockout" }, { value: "group", label: "Groups" }]} value={stage} onChange={(value) => setStage(value as "knockout" | "group")} />
          <Field label="Round" type="number" min={1} max={64} value={round} onChange={(event) => setRound(event.target.value)} hint="1 is the first round" />
        </div>
      )}
      {scope === "day" && <Field label="Day" type="date" value={day} min={t.starts_on} max={t.ends_on} onChange={(event) => setDay(event.target.value)} hint="Venue local" />}
      {scope === "session" && (
        <SelectField
          label="Session"
          options={sessions.map((session) => ({ value: session.id, label: `${session.name || "Session"} · ${session.day} ${session.starts.slice(0, 5)}–${session.ends.slice(0, 5)}` }))}
          value={sessionId}
          onChange={setSessionId}
          hint={schedule.isSuccess && sessions.length === 0 ? "This tournament has no sessions; choose a day instead." : undefined}
        />
      )}
      {make.error && <FormAlert>{errorMessage(make.error, "We couldn't draft the announcement.")}</FormAlert>}
      <Button type="submit" disabled={make.isPending} className="self-start">
        <Sparkles aria-hidden /> {make.isPending ? "Drafting…" : "Draft announcement"}
      </Button>
    </form>
  )
}

function Draft({ post, tournamentId }: { post: Announcement; tournamentId: string }) {
  const refresh = useRefresh(tournamentId)
  const [title, setTitle] = useState(post.title)
  const [body, setBody] = useState(post.body)
  const [notify, setNotify] = useState(true)
  const [cardVersion, setCardVersion] = useState(0)
  const changed = title !== post.title || body !== post.body
  const save = useMutation({
    mutationFn: () => editAnnouncement(tournamentId, post.id, { title, body }),
    onSuccess: () => {
      setCardVersion((version) => version + 1)
      void refresh()
    },
  })
  const publish = useMutation({
    mutationFn: async () => {
      if (changed) await editAnnouncement(tournamentId, post.id, { title, body })
      return publishAnnouncement(tournamentId, post.id, notify)
    },
    onSuccess: () => void refresh(),
  })
  const remove = useMutation({ mutationFn: () => deleteAnnouncement(tournamentId, post.id), onSuccess: () => void refresh() })
  const failed = save.error ?? publish.error ?? remove.error
  return (
    <section aria-label={`Draft: ${post.title}`} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <p className="text-sm font-semibold text-muted-foreground">{post.amends_id ? "Draft amendment" : "Draft"}</p>
      <Field label="Title" value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
      <TextAreaField label="Text" value={body} maxLength={5000} rows={Math.min(24, body.split("\n").length + 2)} onChange={(event) => setBody(event.target.value)} className="font-mono text-sm" />
      <details className="rounded-lg border p-3">
        <summary className="min-h-12 cursor-pointer py-3 font-semibold">Preview as a post (WhatsApp, social media)</summary>
        <pre className="text-sm whitespace-pre-wrap break-words">{`${title}\n\n${body}`}</pre>
      </details>
      <details className="rounded-lg border p-3">
        <summary className="min-h-12 cursor-pointer py-3 font-semibold">Preview the image card</summary>
        {changed && <p className="text-sm text-muted-foreground">Save to see your changes on the card.</p>}
        <img src={`${announcementCardUrl(tournamentId, post.id)}?v=${cardVersion}`} alt={`Image card: ${post.title}`} className="mt-2 h-auto w-full max-w-[420px] rounded-lg border" />
      </details>
      <a href={announcementPdfUrl(tournamentId, post.id)} className="self-start font-semibold text-brand-blue underline-offset-4 hover:underline">
        Download as PDF{changed ? " (as last saved)" : ""}
      </a>
      <label className="flex min-h-12 items-center gap-3">
        <input type="checkbox" checked={notify} onChange={(event) => setNotify(event.target.checked)} className="size-5" />
        Tell the tournament's players when it is published
      </label>
      {failed && <FormAlert>{errorMessage(failed, "That didn't work.")}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={!changed || save.isPending} onClick={() => save.mutate()}>
          Save draft
        </Button>
        <Button type="button" disabled={publish.isPending || !title.trim() || !body.trim()} onClick={() => publish.mutate()}>
          <Send aria-hidden /> {publish.isPending ? "Publishing…" : "Publish"}
        </Button>
        <Button type="button" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
          <Trash2 aria-hidden /> Delete draft
        </Button>
      </div>
    </section>
  )
}

function PublishedRow({ post, tournamentId, timeZone }: { post: Announcement; tournamentId: string; timeZone: string }) {
  const refresh = useRefresh(tournamentId)
  const amend = useMutation({ mutationFn: () => amendAnnouncement(tournamentId, post.id), onSuccess: () => void refresh() })
  return (
    <div className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="font-semibold">{post.title}</p>
      <p className="text-sm text-muted-foreground">Published {post.published_at ? formatInstant(post.published_at, timeZone) : ""}</p>
      {post.outdated_at && !post.amended_by_id && <p className="text-sm font-semibold">A result in it was corrected since. Publish an amendment.</p>}
      {post.amended_by_id && <p className="text-sm text-muted-foreground">Amended.</p>}
      {amend.error && <FormAlert>{errorMessage(amend.error, "We couldn't draft the amendment.")}</FormAlert>}
      {!post.amended_by_id && (
        <Button type="button" variant={post.outdated_at ? "default" : "outline"} size="sm" className="self-start" disabled={amend.isPending} onClick={() => amend.mutate()}>
          Draft an amendment
        </Button>
      )}
    </div>
  )
}
