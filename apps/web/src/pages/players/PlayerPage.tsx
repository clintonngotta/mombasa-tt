import { Link, useLocation, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Building2, TrendingUp } from "lucide-react"
import { NavCard } from "@/components/layout/NavCard"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { Avatar } from "@/components/profile/Avatar"
import { buttonVariants } from "@/components/ui/button"
import { ApiError, errorMessage } from "@/lib/api"
import { useMe } from "@/lib/session"
import { DETAIL_LABEL, PUBLISHED_DETAILS, detailText, getPlayer, playerKeys } from "@/lib/profile"

/**
 * A listed player's page: directory card plus only the details they published (REQ-006). Signed out
 * (TASK-035) it is there only for players with competition records, and shows their name and ratings:
 * the photo, clubs and details are for signed-in players, as the directory is.
 */
export function PlayerPage() {
  const { id = "" } = useParams()
  const me = useMe()
  const signedOut = me.isError
  const back = signedOut ? <BackLink to="/rankings">Rankings</BackLink> : <BackLink to="/players">Players</BackLink>
  const player = useQuery({ queryKey: playerKeys.detail(id), queryFn: () => getPlayer(id), enabled: !me.isPending })

  if (player.isPending) {
    return (
      <div className="flex max-w-[640px] flex-col gap-4">
        {!me.isPending && back}
        <p className="text-muted-foreground">Loading player…</p>
      </div>
    )
  }
  if (player.isError) {
    const gone = player.error instanceof ApiError && player.error.status === 404
    return (
      <div className="flex max-w-[640px] flex-col gap-4">
        {back}
        <FormAlert>
          {gone ? (signedOut ? "This player has no public page." : "This player isn't listed in the directory.") : errorMessage(player.error, "We couldn't load this player.")}
        </FormAlert>
      </div>
    )
  }

  const data = player.data
  const details = PUBLISHED_DETAILS.map((detail) => ({ detail, text: detailText(data, detail) })).filter((d) => d.text)

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      {back}
      <header className="flex items-center gap-4">
        <Avatar link={data.avatar} className="size-16" />
        <div className="flex min-w-0 flex-col">
          <h1 className="text-[28px] leading-8 font-bold">{data.display_name}</h1>
          {data.nickname && <p className="text-muted-foreground">“{data.nickname}”</p>}
        </div>
      </header>

      {!signedOut && (
        <section aria-labelledby="clubs-heading" className="flex flex-col gap-2">
          <h2 id="clubs-heading" className="text-xl font-bold">
            Clubs
          </h2>
          {data.clubs.length === 0 ? (
            <p className="text-muted-foreground">No club listed.</p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {data.clubs.map((club) => (
                <li key={club} className="flex items-center gap-1.5 rounded-full border bg-card px-3 py-1.5 text-sm font-semibold">
                  <Building2 aria-hidden className="size-4 text-brand-blue" /> {club}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <NavCard to={`/ratings/${id}`} icon={TrendingUp} title="Ratings" description="Singles and doubles ratings and the matches behind them" />

      {signedOut && <SignedOutNote />}

      {details.length > 0 && (
        <section aria-labelledby="about-heading" className="flex flex-col gap-2">
          <h2 id="about-heading" className="text-xl font-bold">
            About
          </h2>
          <dl className="grid grid-cols-1 gap-3 rounded-xl border bg-card p-4 sm:grid-cols-2">
            {details.map(({ detail, text }) => (
              <div key={detail} className={detail === "bio" ? "sm:col-span-2" : undefined}>
                <dt className="text-sm text-muted-foreground">{DETAIL_LABEL[detail]}</dt>
                <dd className="font-semibold whitespace-pre-line">{text}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
    </div>
  )
}

/** Signed out, the page says why it is short and offers the way to the rest. */
function SignedOutNote() {
  const { pathname } = useLocation()
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border bg-card p-4">
      <p className="text-muted-foreground">Log in to see this player's clubs and the details they share with other players.</p>
      <Link to={`/login?next=${encodeURIComponent(pathname)}`} className={buttonVariants({ variant: "outline" })}>
        Log in
      </Link>
    </div>
  )
}
