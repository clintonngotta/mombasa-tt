import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ClipboardCheck, Landmark, Stamp } from "lucide-react"
import { OrgLinkRow } from "@/components/clubs/OrganizationLinks"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { KIND_LABEL, type OrganizationKind } from "@/lib/clubs"
import { getOverview, platformKeys } from "@/lib/platform"

const TOURNAMENT_LABEL = { draft: "Draft", published: "Published", in_progress: "In progress", completed: "Completed", cancelled: "Cancelled" } as const

function Figure({ label, value, to, note }: { label: string; value: number; to?: string; note?: string }) {
  const body = (
    <>
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-[28px] leading-8 font-bold tabular-nums">{value.toLocaleString("en-KE")}</span>
      {note && <span className="text-sm text-muted-foreground">{note}</span>}
    </>
  )
  const box = "flex flex-col gap-1 rounded-xl border bg-card p-4"
  return to ? (
    <Link to={to} className={`${box} outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50`}>
      {body}
    </Link>
  ) : (
    <div className={box}>{body}</div>
  )
}

function Breakdown({ title, rows }: { title: string; rows: [string, number][] }) {
  return (
    <section className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <h2 className="font-semibold">{title}</h2>
      <dl className="flex flex-col">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 border-b py-2 last:border-b-0">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="font-semibold tabular-nums">{value.toLocaleString("en-KE")}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** The back office's first page: how big the platform is and what is waiting for the platform to act. */
export function AdminOverviewPage() {
  const overview = useQuery({ queryKey: platformKeys.overview, queryFn: getOverview })
  if (overview.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (overview.isError) return <FormAlert>{errorMessage(overview.error, "We couldn't load the overview.")}</FormAlert>
  const data = overview.data
  const waiting = data.tournaments_awaiting_approval + data.events_awaiting_review
  const organizations = Object.values(data.organizations).reduce((sum, n) => sum + n, 0)
  const tournaments = Object.values(data.tournaments).reduce((sum, n) => sum + n, 0)

  return (
    <div className="flex flex-col gap-8">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Figure label="Accounts" value={data.accounts} to="/admin/accounts" note={`${data.accounts_new} new in 30 days`} />
        <Figure label="Organizations" value={organizations} to="/admin/organizations" />
        <Figure label="Tournaments" value={tournaments} />
        <Figure label="Super admins" value={data.platform_admins} note={`${data.accounts_inactive} accounts switched off`} />
      </div>

      <section aria-labelledby="waiting-heading" className="flex flex-col gap-3">
        <h2 id="waiting-heading" className="text-xl font-bold">
          Waiting for the platform
        </h2>
        {waiting === 0 && <p className="text-muted-foreground">Nothing is waiting.</p>}
        <OrgLinkRow to="/regional" icon={<Stamp aria-hidden className="size-5 text-brand-blue" />}>
          Tournaments asking for approval ({data.tournaments_awaiting_approval})
        </OrgLinkRow>
        <OrgLinkRow to="/events/review" icon={<ClipboardCheck aria-hidden className="size-5 text-brand-blue" />}>
          Events listed from elsewhere, waiting for review ({data.events_awaiting_review})
        </OrgLinkRow>
        <OrgLinkRow to="/regional" icon={<Landmark aria-hidden className="size-5 text-brand-blue" />}>
          Governing bodies: create a regional or national body
        </OrgLinkRow>
      </section>

      <div className="grid items-start gap-3 md:grid-cols-2">
        <Breakdown title="Organizations by kind" rows={Object.entries(data.organizations).map(([kind, n]) => [KIND_LABEL[kind as OrganizationKind] ?? kind, n])} />
        <Breakdown title="Tournaments by status" rows={Object.entries(data.tournaments).map(([state, n]) => [TOURNAMENT_LABEL[state as keyof typeof TOURNAMENT_LABEL] ?? state, n])} />
      </div>
    </div>
  )
}
