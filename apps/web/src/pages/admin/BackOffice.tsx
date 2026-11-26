import { useState, type FormEvent, type ReactNode } from "react"
import { NavLink, Outlet } from "react-router-dom"
import { Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useMe } from "@/lib/session"
import { PAGE_SIZE } from "@/lib/platform"
import { cn } from "@/lib/utils"

const SECTIONS = [
  { to: "/admin", label: "Overview", end: true },
  { to: "/admin/accounts", label: "Accounts" },
  { to: "/admin/organizations", label: "Organizations" },
  { to: "/admin/places", label: "Places" },
]

/** The platform's back office (REQ-056): the frame around every /admin page. Only a platform super admin
 * gets in; anyone else signed in is told the page isn't theirs, and the API refuses them whatever the
 * browser shows. Signed-out visitors are sent to log in first (RequireAuth, around this). */
export function BackOffice() {
  const me = useMe()
  if (!me.data?.is_platform_admin) {
    return (
      <div className="flex max-w-[640px] flex-col gap-2">
        <h1 className="text-[32px] leading-9 font-bold">Page not found</h1>
        <p className="text-muted-foreground">There is nothing for this account at this address.</p>
      </div>
    )
  }
  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Back office</h1>
        <p className="text-muted-foreground">Platform super admin · signed in as {me.data.display_name}</p>
      </div>
      <nav aria-label="Back office" className="-mx-1 flex gap-1 overflow-x-auto border-b px-1">
        {SECTIONS.map((section) => (
          <NavLink
            key={section.to}
            to={section.to}
            end={section.end}
            className={({ isActive }) =>
              cn(
                "flex h-12 shrink-0 items-center border-b-2 border-transparent px-3 font-semibold text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
                isActive && "border-brand-blue text-brand-blue"
              )
            }
          >
            {section.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  )
}

/** A search box that searches when submitted, so each keystroke isn't a request. */
export function SearchBox({ label, placeholder, onSearch }: { label: string; placeholder: string; onSearch: (term: string) => void }) {
  const [input, setInput] = useState("")
  function onSubmit(event: FormEvent) {
    event.preventDefault()
    onSearch(input.trim())
  }
  return (
    <form role="search" onSubmit={onSubmit} className="flex min-w-0 flex-1 gap-2">
      <Input type="search" aria-label={label} placeholder={placeholder} maxLength={80} value={input} onChange={(e) => setInput(e.target.value)} />
      <Button type="submit" size="icon" aria-label="Search">
        <Search aria-hidden className="size-5" />
      </Button>
    </form>
  )
}

export function Pager({ page, count, onPage }: { page: number; count: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE))
  if (pages === 1) return null
  return (
    <nav aria-label="Pages" className="flex items-center justify-between gap-3">
      <Button variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </Button>
      <p className="text-sm text-muted-foreground">
        Page {page} of {pages}
      </p>
      <Button variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </Button>
    </nav>
  )
}

export function Tag({ tone = "plain", children }: { tone?: "plain" | "strong" | "warn"; children: ReactNode }) {
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-xs font-semibold",
        tone === "strong" && "border-brand-blue text-brand-blue",
        tone === "warn" && "border-destructive text-destructive",
        tone === "plain" && "text-muted-foreground"
      )}
    >
      {children}
    </span>
  )
}
