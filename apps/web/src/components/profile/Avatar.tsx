import { useState } from "react"
import { UserRound } from "lucide-react"
import { apiOriginUrl } from "@/lib/api"
import { getAttachmentLink, type AttachmentLink } from "@/lib/profile"
import { cn } from "@/lib/utils"

/**
 * A player's picture, or a placeholder when they have none. Decorative: the name is always next to it.
 * Picture links expire after a few minutes, so a failed load asks once for a new link before giving up.
 */
export function Avatar({ link, className }: { link: AttachmentLink | null; className?: string }) {
  const [retry, setRetry] = useState<{ after: string; url: string | null } | null>(null)
  const url = link ? (retry?.after === link.url ? retry.url : link.url) : null

  function onError() {
    if (!link) return
    if (retry?.after === link.url) return setRetry({ after: link.url, url: null })
    getAttachmentLink(link.id)
      .then((fresh) => setRetry({ after: link.url, url: fresh.url }))
      .catch(() => setRetry({ after: link.url, url: null }))
  }

  return (
    <span className={cn("flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-selected", className)}>
      {url ? (
        <img src={apiOriginUrl(url)} alt="" className="size-full object-cover" onError={onError} />
      ) : (
        <UserRound aria-hidden className="size-1/2 text-brand-blue" />
      )}
    </span>
  )
}
