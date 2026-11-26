import { useEffect, useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { ChevronDown, Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { buttonVariants } from "@/components/ui/button"
import { articleText, TOPICS, type Article } from "@/pages/help/topics"
import { cn } from "@/lib/utils"

/** The help centre: how to do the common things, step by step. Open to everyone, signed in or not. */
export function HelpPage() {
  const { hash } = useLocation()
  const wanted = decodeURIComponent(hash.slice(1))
  const [term, setTerm] = useState("")
  const words = term.toLowerCase().split(/\s+/).filter(Boolean).slice(0, 8)
  const matches = (article: Article) => words.every((word) => articleText(article).includes(word))
  const topics = TOPICS.map((topic) => ({ ...topic, articles: topic.articles.filter(matches) })).filter((topic) => topic.articles.length > 0)
  const found = topics.reduce((sum, topic) => sum + topic.articles.length, 0)

  // A link to /help#join-a-club opens that answer and brings it into view.
  useEffect(() => {
    if (wanted) document.getElementById(wanted)?.scrollIntoView({ block: "start" })
  }, [wanted])

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Help</h1>
        <p className="text-muted-foreground">How to enter tournaments, follow matches, join a club, find somewhere to play and run your own events.</p>
      </div>

      <div role="search" className="relative">
        <label htmlFor="help-search" className="sr-only">
          Search help
        </label>
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-muted-foreground" />
        <Input id="help-search" type="search" maxLength={80} placeholder="Search help, e.g. check in" className="pl-10" value={term} onChange={(e) => setTerm(e.target.value)} />
      </div>

      {!term && (
        <nav aria-label="Help topics" className="grid gap-2 sm:grid-cols-2">
          {TOPICS.map(({ id, title, icon: Icon }) => (
            <a key={id} href={`#${id}`} className="flex min-h-12 items-center gap-3 rounded-xl border bg-card px-4 py-3 font-semibold outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50">
              <Icon aria-hidden className="size-5 shrink-0 text-brand-blue" /> {title}
            </a>
          ))}
        </nav>
      )}

      <p aria-live="polite" className={cn("text-sm text-muted-foreground", !term && "sr-only")}>
        {term ? (found === 0 ? `Nothing matches “${term}”. Try fewer or different words.` : `${found} ${found === 1 ? "answer" : "answers"}`) : ""}
      </p>

      {topics.map(({ id, title, icon: Icon, articles }) => (
        <section key={id} id={id} aria-labelledby={`${id}-heading`} className="flex scroll-mt-20 flex-col gap-2">
          <h2 id={`${id}-heading`} className="flex items-center gap-2 text-2xl font-bold">
            <Icon aria-hidden className="size-6 text-brand-blue" /> {title}
          </h2>
          {articles.map((article) => (
            <Answer key={`${article.id}:${!!term || article.id === wanted}`} article={article} open={!!term || article.id === wanted} />
          ))}
        </section>
      ))}

      <p className="text-sm text-muted-foreground">
        Still stuck? For a question about one tournament or club, its organizers or admin can help: their names are on its page.
      </p>
    </div>
  )
}

function Answer({ article, open }: { article: Article; open: boolean }) {
  return (
    // Its key (set by the list) reopens it when a search or a link asks for it; otherwise the reader opens and closes it.
    <details id={article.id} open={open} className="group scroll-mt-20 rounded-xl border bg-card">
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        {article.question}
        <ChevronDown aria-hidden className="size-5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="flex flex-col gap-3 px-4 pb-4">
        {article.steps && (
          <ol className="flex list-decimal flex-col gap-1.5 pl-5">
            {article.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        )}
        {article.notes?.map((note) => (
          <p key={note} className={cn(article.steps && "text-muted-foreground")}>
            {note}
          </p>
        ))}
        {article.link && (
          <Link to={article.link.to} className={buttonVariants({ variant: "outline", className: "self-start" })}>
            {article.link.label}
          </Link>
        )}
      </div>
    </details>
  )
}
