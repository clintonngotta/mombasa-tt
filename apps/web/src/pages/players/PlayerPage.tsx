import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Building2, UserRound } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { ApiError, errorMessage } from "@/lib/api"
import { DETAIL_LABEL, PUBLISHED_DETAILS, detailText, getPlayer, playerKeys } from "@/lib/profile"

/** A listed player's page: directory card plus only the details they published (REQ-006). */
export function PlayerPage() {
  const { id = "" } = useParams()
  const player = useQuery({ queryKey: playerKeys.detail(id), queryFn: () => getPlayer(id) })

  if (player.isPending) {
    return (
      <div className="flex max-w-[640px] flex-col gap-4">
        <BackLink to="/players">Players</BackLink>
        <p className="text-muted-foreground">Loading player…</p>
      </div>
    )
  }
  if (player.isError) {
    const gone = player.error instanceof ApiError && player.error.status === 404
    return (
      <div className="flex max-w-[640px] flex-col gap-4">
        <BackLink to="/players">Players</BackLink>
        <FormAlert>
          {gone ? "This player isn't listed in the directory." : errorMessage(player.error, "We couldn't load this player.")}
        </FormAlert>
      </div>
    )
  }

  const data = player.data
  const details = PUBLISHED_DETAILS.map((detail) => ({ detail, text: detailText(data, detail) })).filter((d) => d.text)

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <BackLink to="/players">Players</BackLink>
      <header className="flex items-center gap-4">
        <span className="flex size-16 shrink-0 items-center justify-center rounded-full bg-surface-selected">
          <UserRound aria-hidden className="size-8 text-brand-blue" />
        </span>
        <div className="flex min-w-0 flex-col">
          <h1 className="text-[28px] leading-8 font-bold">{data.display_name}</h1>
          {data.nickname && <p className="text-muted-foreground">“{data.nickname}”</p>}
        </div>
      </header>

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
