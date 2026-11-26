import { useState, type FormEvent } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, Newspaper, Plus, Trash2 } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { ChoiceGroup } from "@/components/forms/ChoiceGroup"
import { SelectField, TextAreaField } from "@/components/forms/SelectField"
import { MeetingsPanel } from "@/pages/region/MeetingPages"
import { OrganizeAsBody, OverseenTournaments } from "@/components/region/RegionTournaments"
import { api, ApiError, errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { can, isBodyKind, useActiveMembership, type Membership } from "@/lib/clubs"
import { formatDay, formatDayRange } from "@/lib/dates"
import {
  addAgendaItem,
  AGENDA_KIND_LABEL,
  createArticle,
  deleteAgendaItem,
  describeSponsorship,
  getArticle,
  listAgenda,
  listArticles,
  listRegionClubs,
  listSponsorships,
  offerSponsorship,
  publishArticle,
  regionKeys,
  withdrawSponsorship,
  type AgendaKind,
  type Article,
} from "@/lib/regions"
import { listTournaments, type Tournament } from "@/lib/tournaments"
import type { Schemas } from "@/lib/schema"
import { cn } from "@/lib/utils"

type Tab = "clubs" | "agenda" | "articles" | "meetings" | "sponsorships" | "tournaments" | "approvals"
const TABS: { value: Tab; label: string }[] = [
  { value: "agenda", label: "Agenda" },
  { value: "clubs", label: "Clubs" },
  { value: "articles", label: "Articles" },
  { value: "meetings", label: "Meetings" },
  { value: "sponsorships", label: "Sponsorships" },
  { value: "tournaments", label: "Tournaments" },
  { value: "approvals", label: "Approvals" },
]

/** A regional body's home (REQ-048): its region's clubs, the yearly agenda, articles to clubs, meetings,
 * sponsorships and the tournaments waiting for its approval. */
export function RegionPage() {
  const { active } = useActiveMembership()
  const [params, setParams] = useSearchParams()
  const tab = (TABS.find((t) => t.value === params.get("tab"))?.value ?? "agenda") as Tab
  if (!active) return null
  if (!isBodyKind(active.organization.kind)) {
    return <FormAlert>Switch to your regional or national body to see this page.</FormAlert>
  }
  const body = active.organization

  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <BackLink to="/club">{body.name}</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">{body.name}</h1>
        <p className="text-muted-foreground">{body.kind === "national_body" ? `National body for ${body.country}` : `Regional body for ${body.region}`}</p>
      </div>
      <div role="tablist" aria-label="Region" className="flex gap-1 overflow-x-auto border-b">
        {TABS.map((t) => (
          <button
            key={t.value}
            role="tab"
            type="button"
            aria-selected={tab === t.value}
            onClick={() => setParams(t.value === "agenda" ? {} : { tab: t.value })}
            className={cn(
              "-mb-px min-h-12 shrink-0 border-b-2 px-4 font-semibold whitespace-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              tab === t.value ? "border-brand-blue text-brand-blue" : "border-transparent text-muted-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="flex flex-col gap-6">
        {tab === "agenda" && <Agenda membership={active} />}
        {tab === "clubs" && <Clubs orgId={body.id} />}
        {tab === "articles" && <Articles membership={active} />}
        {tab === "meetings" && <MeetingsPanel orgId={body.id} timeZone={body.timezone ?? "Africa/Nairobi"} staff={can(active, "governance.manage")} body />}
        {tab === "sponsorships" && <Sponsorships membership={active} />}
        {tab === "tournaments" && (
          <>
            <OrganizeAsBody body={active} />
            <OverseenTournaments />
          </>
        )}
        {tab === "approvals" && <Approvals />}
      </div>
    </div>
  )
}

function Clubs({ orgId }: { orgId: string }) {
  const clubs = useQuery({ queryKey: regionKeys.clubs(orgId), queryFn: () => listRegionClubs(orgId) })
  return (
    <section aria-label="Clubs of the region" className="flex flex-col gap-3">
      {clubs.isError && <FormAlert>{errorMessage(clubs.error)}</FormAlert>}
      {clubs.isSuccess && clubs.data.length === 0 && <p className="text-muted-foreground">No clubs have registered in the region yet.</p>}
      <ul className="flex flex-col gap-2">
        {clubs.data?.map((club) => (
          <li key={club.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold">{club.name}</span>
              <span className="text-sm text-muted-foreground">
                {club.town} · {club.kind === "facility" ? "Facility" : club.kind === "club_facility" ? "Club and facility" : "Club"}
              </span>
            </span>
            <span className="text-sm text-muted-foreground">
              {club.members} member{club.members === 1 ? "" : "s"} · {club.upcoming_tournaments} upcoming tournament{club.upcoming_tournaments === 1 ? "" : "s"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Agenda({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const queryClient = useQueryClient()
  const [year, setYear] = useState(() => new Date().getFullYear())
  const agenda = useQuery({ queryKey: regionKeys.agenda(orgId, year), queryFn: () => listAgenda(orgId, year) })
  const staff = can(membership, "governance.manage")
  const remove = useMutation({ mutationFn: (id: string) => deleteAgendaItem(orgId, id), onSuccess: () => queryClient.invalidateQueries({ queryKey: regionKeys.all }) })
  const byMonth = new Map<string, NonNullable<typeof agenda.data>>()
  for (const item of agenda.data ?? []) {
    const month = item.starts_on.slice(0, 7) < `${year}-01` ? `${year}-01` : item.starts_on.slice(0, 7)
    byMonth.set(month, [...(byMonth.get(month) ?? []), item])
  }

  return (
    <section aria-label="Yearly agenda" className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon" aria-label="Previous year" onClick={() => setYear(year - 1)}>
          <ChevronLeft aria-hidden className="size-5" />
        </Button>
        <h2 className="min-w-20 text-center text-xl font-bold tabular-nums">{year}</h2>
        <Button variant="outline" size="icon" aria-label="Next year" onClick={() => setYear(year + 1)}>
          <ChevronRight aria-hidden className="size-5" />
        </Button>
      </div>
      {agenda.isError && <FormAlert>{errorMessage(agenda.error)}</FormAlert>}
      {remove.isError && <FormAlert>{errorMessage(remove.error)}</FormAlert>}
      {agenda.isSuccess && agenda.data.length === 0 && <p className="text-muted-foreground">Nothing on the {year} agenda yet.</p>}
      {[...byMonth.entries()].map(([month, items]) => (
        <div key={month} className="flex flex-col gap-2">
          <h3 className="font-semibold">{new Date(`${month}-01T12:00:00`).toLocaleDateString("en-KE", { month: "long", year: "numeric" })}</h3>
          <ul className="flex flex-col gap-2">
            {items.map((item) => (
              <li key={item.id} className={ROW}>
                <span className="w-32 shrink-0 text-sm font-semibold">{item.starts_on === item.ends_on ? formatDay(item.starts_on) : formatDayRange(item.starts_on, item.ends_on ?? item.starts_on)}</span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold">
                    {item.tournament ? <Link to={`/tournaments/${item.tournament.id}`} className="text-brand-blue underline-offset-4 hover:underline">{item.title}</Link> : item.title}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {AGENDA_KIND_LABEL[item.kind ?? "event"]}
                    {item.description && ` · ${item.description}`}
                  </span>
                </span>
                {staff && (
                  <Button variant="ghost" size="icon" aria-label={`Remove ${item.title}`} disabled={remove.isPending} onClick={() => remove.mutate(item.id)}>
                    <Trash2 aria-hidden className="size-5" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {staff && <NewAgendaItem orgId={orgId} region={membership.organization.region ?? ""} />}
    </section>
  )
}

function NewAgendaItem({ orgId, region }: { orgId: string; region: string }) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<AgendaKind>("tournament")
  const [title, setTitle] = useState("")
  const [startsOn, setStartsOn] = useState("")
  const [endsOn, setEndsOn] = useState("")
  const [description, setDescription] = useState("")
  const [tournament, setTournament] = useState("")
  const cups = useQuery({ queryKey: ["region", "cups"], queryFn: () => listTournaments("upcoming", "", "") })
  const regional = (cups.data?.results ?? []).filter((t: Tournament) => t.organization.region?.toLowerCase() === region.toLowerCase())
  const add = useMutation({
    mutationFn: () =>
      addAgendaItem(orgId, {
        kind,
        title: title.trim(),
        starts_on: startsOn,
        ...(endsOn ? { ends_on: endsOn } : {}),
        description: description.trim(),
        ...(tournament ? { tournament_id: tournament } : {}),
      }),
    onSuccess: async () => {
      setTitle("")
      setStartsOn("")
      setEndsOn("")
      setDescription("")
      setTournament("")
      await queryClient.invalidateQueries({ queryKey: regionKeys.all })
    },
  })
  const fields: Record<string, string | undefined> = add.error instanceof ApiError ? add.error.fieldErrors() : {}

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    add.mutate()
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h3 className="text-lg font-bold">Add to the agenda</h3>
      {add.isError && <FormAlert>{errorMessage(add.error)}</FormAlert>}
      <ChoiceGroup legend="What" columns={3} options={(Object.keys(AGENDA_KIND_LABEL) as AgendaKind[]).map((k) => ({ value: k, label: AGENDA_KIND_LABEL[k] }))} value={kind} onChange={setKind} />
      <Field label="Title" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} error={fields.title} placeholder="e.g. Coast Open, AGM, entries close" />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="From" type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} error={fields.starts_on} />
        <Field label="To" optional type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} error={fields.ends_on} />
      </div>
      {kind === "tournament" && regional.length > 0 && (
        <SelectField
          label="Tournament"
          optional
          options={[{ value: "", label: "Not published yet" }, ...regional.map((t) => ({ value: t.id, label: `${t.name} · ${t.organization.name}` }))]}
          value={tournament}
          onChange={setTournament}
          error={fields.tournament_id}
        />
      )}
      <TextAreaField label="Notes" optional rows={2} maxLength={1000} value={description} onChange={(e) => setDescription(e.target.value)} />
      <Button type="submit" className="self-start" disabled={add.isPending || !title.trim() || !startsOn}>
        <Plus aria-hidden className="size-4" /> Add
      </Button>
    </form>
  )
}

function Articles({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const queryClient = useQueryClient()
  const articles = useQuery({ queryKey: regionKeys.articles(orgId), queryFn: () => listArticles(orgId) })
  const staff = can(membership, "announcements.manage")
  const publish = useMutation({ mutationFn: (id: string) => publishArticle(orgId, id), onSuccess: () => queryClient.invalidateQueries({ queryKey: regionKeys.all }) })
  return (
    <section aria-label="Articles" className="flex flex-col gap-4">
      {articles.isError && <FormAlert>{errorMessage(articles.error)}</FormAlert>}
      {publish.isError && <FormAlert>{errorMessage(publish.error)}</FormAlert>}
      {articles.isSuccess && articles.data.length === 0 && <p className="text-muted-foreground">No articles yet.</p>}
      <ul className="flex flex-col gap-2">
        {articles.data?.map((article) => (
          <li key={article.id} className={ROW}>
            <Newspaper aria-hidden className="size-5 text-brand-blue" />
            <Link to={`/news/${orgId}/${article.id}`} className="flex min-w-0 flex-1 flex-col outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
              <span className="font-semibold">{article.title}</span>
              <span className="text-sm text-muted-foreground">
                {article.status === "draft" ? "Draft" : `Published ${new Date(article.published_at!).toLocaleDateString("en-KE")}`} ·{" "}
                {article.audience === "chosen" ? article.clubs.map((c) => c.name).join(", ") : "All clubs in the region"}
              </span>
            </Link>
            {staff && article.status === "draft" && (
              <Button disabled={publish.isPending} onClick={() => publish.mutate(article.id)}>
                Publish
              </Button>
            )}
          </li>
        ))}
      </ul>
      {staff && <NewArticle orgId={orgId} />}
    </section>
  )
}

function NewArticle({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const clubs = useQuery({ queryKey: regionKeys.clubs(orgId), queryFn: () => listRegionClubs(orgId) })
  const [title, setTitle] = useState("")
  const [summary, setSummary] = useState("")
  const [body, setBody] = useState("")
  const [audience, setAudience] = useState<"region" | "chosen">("region")
  const [chosen, setChosen] = useState<string[]>([])
  const save = useMutation({
    mutationFn: () => createArticle(orgId, { title: title.trim(), summary: summary.trim(), body: body.trim(), audience, club_ids: audience === "chosen" ? chosen : [] }),
    onSuccess: async () => {
      setTitle("")
      setSummary("")
      setBody("")
      setChosen([])
      await queryClient.invalidateQueries({ queryKey: regionKeys.all })
    },
  })
  const fields: Record<string, string | undefined> = save.error instanceof ApiError ? save.error.fieldErrors() : {}

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <h3 className="text-lg font-bold">Write an article</h3>
      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <Field label="Headline" maxLength={140} value={title} onChange={(e) => setTitle(e.target.value)} error={fields.title} />
      <Field label="Summary" optional maxLength={280} value={summary} onChange={(e) => setSummary(e.target.value)} />
      <TextAreaField label="Article" rows={8} maxLength={10000} value={body} onChange={(e) => setBody(e.target.value)} error={fields.body} />
      <ChoiceGroup
        legend="Send to"
        options={[
          { value: "region", label: "Every club in the region" },
          { value: "chosen", label: "Clubs I choose" },
        ]}
        value={audience}
        onChange={setAudience}
      />
      {audience === "chosen" && (
        <ChoiceGroup multiple legend="Clubs" options={(clubs.data ?? []).map((c) => ({ value: c.id, label: c.name }))} value={chosen} onChange={setChosen} error={fields.club_ids} />
      )}
      <p className="text-sm text-muted-foreground">Saved as a draft. Publish it from the list to send it.</p>
      <Button type="submit" className="self-start" disabled={save.isPending || !title.trim() || !body.trim() || (audience === "chosen" && chosen.length === 0)}>
        Save draft
      </Button>
    </form>
  )
}

/** An article as its readers see it. */
export function ArticlePage() {
  const { orgId = "", id = "" } = useParams()
  const article = useQuery({ queryKey: regionKeys.article(orgId, id), queryFn: () => getArticle(orgId, id) })
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Back</BackLink>
      {article.isError && <FormAlert>{errorMessage(article.error, "This article isn't for your club.")}</FormAlert>}
      {article.data && <ArticleView article={article.data} />}
    </div>
  )
}

function ArticleView({ article }: { article: Article }) {
  return (
    <article className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <p className="text-sm font-semibold text-brand-blue">{article.organization.name}</p>
        <h1 className="text-[32px] leading-9 font-bold">{article.title}</h1>
        <p className="text-sm text-muted-foreground">{article.published_at ? new Date(article.published_at).toLocaleDateString("en-KE", { day: "numeric", month: "long", year: "numeric" }) : "Draft"}</p>
      </header>
      {article.summary && <p className="text-lg">{article.summary}</p>}
      <div className="whitespace-pre-wrap">{article.body}</div>
    </article>
  )
}

function Sponsorships({ membership }: { membership: Membership }) {
  const orgId = membership.organization.id
  const queryClient = useQueryClient()
  const offers = useQuery({ queryKey: regionKeys.sponsorships(orgId), queryFn: () => listSponsorships(orgId), enabled: can(membership, "competitions.manage") })
  const withdraw = useMutation({ mutationFn: (id: string) => withdrawSponsorship(orgId, id), onSuccess: () => queryClient.invalidateQueries({ queryKey: regionKeys.all }) })
  if (!can(membership, "competitions.manage")) return <p className="text-muted-foreground">Sponsorships are offered by the body's competition staff.</p>
  return (
    <section aria-label="Sponsorships" className="flex flex-col gap-4">
      {offers.isError && <FormAlert>{errorMessage(offers.error)}</FormAlert>}
      {withdraw.isError && <FormAlert>{errorMessage(withdraw.error)}</FormAlert>}
      {offers.isSuccess && offers.data.length === 0 && <p className="text-muted-foreground">You haven't offered a sponsorship yet.</p>}
      <ul className="flex flex-col gap-2">
        {offers.data?.map((offer) => (
          <li key={offer.id} className={ROW}>
            <span className="flex min-w-0 flex-1 flex-col">
              <Link to={`/tournaments/${offer.tournament.id}`} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
                {offer.tournament.name}
              </Link>
              <span className="text-sm">{describeSponsorship(offer)}</span>
              <span className="text-sm text-muted-foreground">
                {offer.status === "offered" ? "Waiting for the host club" : offer.status[0].toUpperCase() + offer.status.slice(1)}
                {offer.reason && ` · ${offer.reason}`}
              </span>
            </span>
            {(offer.status === "offered" || offer.status === "accepted") && (
              <Button variant="outline" disabled={withdraw.isPending} onClick={() => withdraw.mutate(offer.id)}>
                Withdraw
              </Button>
            )}
          </li>
        ))}
      </ul>
      <OfferSponsorship orgId={orgId} />
    </section>
  )
}

function OfferSponsorship({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient()
  const cups = useQuery({ queryKey: ["region", "cups"], queryFn: () => listTournaments("upcoming", "", "") })
  const [tournament, setTournament] = useState("")
  const [amount, setAmount] = useState("")
  const [goods, setGoods] = useState<{ item: string; quantity: string }[]>([])
  const [conditions, setConditions] = useState("")
  const offer = useMutation({
    mutationFn: () =>
      offerSponsorship(orgId, {
        tournament_id: tournament,
        amount_minor: amount.trim() ? Math.round(Number(amount) * 100) : null,
        in_kind: goods.filter((g) => g.item.trim()).map((g) => ({ item: g.item.trim(), quantity: Number(g.quantity) || 1 })),
        conditions: conditions.trim(),
      }),
    onSuccess: async () => {
      setTournament("")
      setAmount("")
      setGoods([])
      setConditions("")
      await queryClient.invalidateQueries({ queryKey: regionKeys.all })
    },
  })
  const fields: Record<string, string | undefined> = offer.error instanceof ApiError ? offer.error.fieldErrors() : {}
  const options = (cups.data?.results ?? []).filter((t) => t.organization.id !== orgId).map((t) => ({ value: t.id, label: `${t.name} · ${t.organization.name}` }))

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        offer.mutate()
      }}
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <h3 className="text-lg font-bold">Offer a sponsorship</h3>
      {offer.isError && <FormAlert>{errorMessage(offer.error)}</FormAlert>}
      <SelectField label="Tournament" options={options} value={tournament} onChange={setTournament} error={fields.tournament_id} placeholder="Choose an upcoming tournament" />
      <Field label="Amount (KES)" optional inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} error={fields.amount_minor} />
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 font-semibold">
          Goods <span className="font-normal text-muted-foreground">(optional)</span>
        </legend>
        {goods.map((g, i) => (
          <div key={i} className="grid grid-cols-[1fr_6rem_auto] items-end gap-2">
            <Field label="Item" value={g.item} maxLength={80} onChange={(e) => setGoods(goods.map((x, j) => (j === i ? { ...x, item: e.target.value } : x)))} placeholder="Balls, trophies, a table" />
            <Field label="How many" inputMode="numeric" value={g.quantity} onChange={(e) => setGoods(goods.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} />
            <Button type="button" variant="outline" size="icon" aria-label={`Remove ${g.item || "item"}`} onClick={() => setGoods(goods.filter((_, j) => j !== i))}>
              <Trash2 aria-hidden className="size-5" />
            </Button>
          </div>
        ))}
        <Button type="button" variant="ghost" className="self-start" disabled={goods.length >= 20} onClick={() => setGoods([...goods, { item: "", quantity: "1" }])}>
          <Plus aria-hidden className="size-4" /> Add goods
        </Button>
      </fieldset>
      <TextAreaField label="Conditions" optional rows={2} maxLength={1000} value={conditions} onChange={(e) => setConditions(e.target.value)} placeholder="e.g. Our banner at the venue; a regional official presents the trophies" />
      <Button type="submit" className="self-start" disabled={offer.isPending || !tournament || (!amount.trim() && !goods.some((g) => g.item.trim()))}>
        Send offer
      </Button>
    </form>
  )
}

export function Approvals() {
  const pending = useQuery({ queryKey: ["tournaments", "awaiting-approval"], queryFn: () => api<Schemas["PaginatedTournamentList"]>("/tournaments/awaiting-approval/") })
  return (
    <section aria-label="Waiting for approval" className="flex flex-col gap-3">
      <p className="text-muted-foreground">Regional tournaments in your region that their hosts asked you to approve. Open one to publish it or decline.</p>
      {pending.isError && <FormAlert>{errorMessage(pending.error)}</FormAlert>}
      {pending.isSuccess && pending.data.results.length === 0 && <p className="text-muted-foreground">Nothing is waiting for you.</p>}
      <ul className="flex flex-col gap-2">
        {pending.data?.results.map((t) => (
          <li key={t.id}>
            <Link to={`/tournaments/${t.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold">{t.name}</span>
                <span className="text-sm text-muted-foreground">
                  {t.organizer.name} · {formatDayRange(t.starts_on, t.ends_on)} · {t.scope}
                </span>
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
