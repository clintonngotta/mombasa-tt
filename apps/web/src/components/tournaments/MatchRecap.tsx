import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Download, Share2 } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { cardUrl, getRecap, recapKey } from "@/lib/recap"

/** The official result for sharing (REQ-018): rating changes once the ledger has them, a card to
 * download and a link to share. Nothing is inferred beyond the official score. */
export function MatchRecap({ tournamentId, eventId, matchId }: { tournamentId: string; eventId: string; matchId: string }) {
  const recap = useQuery({ queryKey: recapKey(matchId), queryFn: () => getRecap(tournamentId, eventId, matchId) })
  const [copied, setCopied] = useState(false)
  const r = recap.data
  if (!r?.official) return null
  const share = async () => {
    const url = window.location.href
    if (navigator.share) {
      await navigator.share({ title: `${r.side_a} v ${r.side_b}`, url }).catch(() => undefined)
    } else {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    }
  }
  return (
    <section aria-labelledby="recap-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="recap-heading" className="text-xl font-bold">
        Recap
      </h2>
      {r.rating === "processing" && <p className="text-muted-foreground">Rating changes are being worked out.</p>}
      {r.rating === "unrated" && <p className="text-muted-foreground">This result doesn't change ratings.</p>}
      {r.rating === "done" && (
        <ul className="flex flex-col gap-1">
          {r.rating_changes.map((c) => (
            <li key={c.user_id} className="flex justify-between gap-2 tabular-nums">
              <span>{c.display_name}</span>
              <span>
                {c.before} → {c.after} <span className={c.delta >= 0 ? "text-success" : "text-destructive"}>({c.delta >= 0 ? "+" : ""}{c.delta})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <a href={cardUrl(tournamentId, eventId, matchId)} download className={buttonVariants({ variant: "outline" })}>
          <Download aria-hidden className="size-4" /> Result card
        </a>
        <Button variant="outline" onClick={() => void share()}>
          <Share2 aria-hidden className="size-4" /> {copied ? "Link copied" : "Share"}
        </Button>
      </div>
    </section>
  )
}
