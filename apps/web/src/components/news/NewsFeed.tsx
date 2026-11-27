import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Copy, FileDown, Image as ImageIcon, ImageDown, Megaphone, Share2 } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { announcementCardUrl, announcementKeys, announcementLink, announcementPdfUrl, announcementsPdfUrl, getAnnouncements, resultsSheetUrl, type Announcement } from "@/lib/announcements"
import { formatInstant } from "@/lib/dates"
import { cn } from "@/lib/utils"

/** The tournament's news feed (REQ-043): its published results announcements, newest first. An outdated
 * post stays as it was published, marked, with the amendment beside it. */
export function NewsFeed({ tournamentId, staff, timeZone }: { tournamentId: string; staff: boolean; timeZone: string }) {
  const feed = useQuery({ queryKey: announcementKeys.feed(tournamentId), queryFn: () => getAnnouncements(tournamentId) })
  const posts = (feed.data?.results ?? []).filter((post) => post.status === "published")
  if (posts.length === 0 && !staff) return null
  return (
    <section aria-labelledby="news-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="news-heading" className="text-2xl font-bold">
          News
        </h2>
        <div className="flex flex-wrap gap-2">
          <a href={resultsSheetUrl(tournamentId, "pdf")} className={buttonVariants({ variant: "outline", size: "sm" })}>
            <FileDown aria-hidden /> Final results (PDF)
          </a>
          <a href={resultsSheetUrl(tournamentId, "png")} download className={buttonVariants({ variant: "outline", size: "sm" })}>
            <ImageDown aria-hidden /> Final results image
          </a>
          {posts.length > 0 && (
            <a href={announcementsPdfUrl(tournamentId)} className={buttonVariants({ variant: "outline", size: "sm" })}>
              <FileDown aria-hidden /> All results as PDF
            </a>
          )}
          {staff && (
            <Link to={`/tournaments/${tournamentId}/announcements`} className={buttonVariants({ variant: "outline", size: "sm" })}>
              <Megaphone aria-hidden /> Results announcements
            </Link>
          )}
        </div>
      </div>
      {posts.length === 0 && <p className="text-muted-foreground">Nothing published yet. Draft a results announcement from the official results.</p>}
      {posts.map((post) => (
        <Post key={post.id} post={post} tournamentId={tournamentId} timeZone={timeZone} />
      ))}
    </section>
  )
}

function Post({ post, tournamentId, timeZone }: { post: Announcement; tournamentId: string; timeZone: string }) {
  const [said, setSaid] = useState("")
  const link = announcementLink(tournamentId, post.id)
  const copy = async (text: string, done: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setSaid(done)
    } catch {
      setSaid("Copying isn't allowed here: select the text instead.")
    }
  }
  const share = async () => {
    if (navigator.share) {
      try {
        await navigator.share({ title: post.title, text: post.body, url: link })
        return
      } catch {
        return // closed without sharing
      }
    }
    await copy(link, "Link copied.")
  }
  return (
    <article id={`news-${post.id}`} aria-labelledby={`news-${post.id}-title`} className={cn("flex flex-col gap-3 rounded-xl border bg-card p-4", post.outdated_at && "border-dashed")}>
      <header className="flex flex-col gap-1">
        <h3 id={`news-${post.id}-title`} className="text-xl font-bold break-words">
          {post.title}
        </h3>
        <p className="text-sm text-muted-foreground">Published {post.published_at ? formatInstant(post.published_at, timeZone) : ""}</p>
      </header>
      {post.amends_id && (
        <p className="text-sm">
          This amends <a href={`#news-${post.amends_id}`} className="font-semibold text-brand-blue underline-offset-4 hover:underline">an earlier post</a>, which stays below as it was published.
        </p>
      )}
      {post.outdated_at && (
        <p role="note" className="rounded-lg bg-secondary px-3 py-2 text-sm">
          A result in this post was corrected after it was published.{" "}
          {post.amended_by_id ? (
            <a href={`#news-${post.amended_by_id}`} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
              Read the amended post
            </a>
          ) : (
            "An amended post will follow."
          )}
        </p>
      )}
      <p className="font-mono text-sm whitespace-pre-wrap break-words">{post.body}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => void copy(post.body, "Text copied.")}>
          <Copy aria-hidden /> Copy text
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => void share()}>
          <Share2 aria-hidden /> Share
        </Button>
        <a href={announcementCardUrl(tournamentId, post.id)} target="_blank" rel="noreferrer" className={buttonVariants({ variant: "outline", size: "sm" })}>
          <ImageIcon aria-hidden /> Image card
        </a>
        <a href={announcementPdfUrl(tournamentId, post.id)} aria-label={`PDF of ${post.title}`} className={buttonVariants({ variant: "outline", size: "sm" })}>
          <FileDown aria-hidden /> PDF
        </a>
      </div>
      <p aria-live="polite" className="text-sm text-muted-foreground">
        {said}
      </p>
    </article>
  )
}
