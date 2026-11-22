import { Link, NavLink, Outlet, useLocation } from "react-router-dom"
import { Ellipsis, LogIn } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Wordmark } from "@/components/brand/Wordmark"
import { OrganizationSwitcher } from "@/components/clubs/OrganizationSwitcher"
import { UpdateBanner } from "@/components/layout/UpdateBanner"
import { OfflineBanner } from "@/components/layout/OfflineBanner"
import { NotificationBell } from "@/components/layout/NotificationBell"
import { MORE_PATH, useNavigation, type NavItem } from "@/lib/navigation"

const MORE: NavItem = { to: MORE_PATH, label: "More", icon: Ellipsis }

// REQ-002: mobile tabs and the web sidebar share the same domain names. Which names show depends on who
// is signed in and the organization they act for (lib/navigation).
export function AppShell() {
  const { signedIn, mode, active, items, tabs, more } = useNavigation()
  const facility = mode === "facility"
  const bar = more.length ? [...tabs, MORE] : tabs
  const location = useLocation()
  const current = currentEntry(location.pathname, [...items, MORE])
  const next = encodeURIComponent(location.pathname + location.search)

  const logIn = (
    <Link to={`/login?next=${next}`} className={buttonVariants({ size: "sm" })}>
      <LogIn aria-hidden className="size-4" /> Log in
    </Link>
  )

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[240px_1fr]">
      {/* Fixed beside the page: only the menu scrolls when it outgrows the screen. */}
      <aside
        className={cn(
          "hidden border-r lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:gap-4 lg:p-4",
          facility ? "border-brand-navy bg-brand-navy text-white" : "bg-card",
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <Wordmark className={cn("px-3 pt-2", facility && "text-white [&>span]:text-brand-cyan")} />
          {signedIn && <NotificationBell />}
        </div>
        {facility && active && (
          <p className="px-3 text-xs font-semibold tracking-wide text-brand-gold uppercase">Facility desk</p>
        )}
        <OrganizationSwitcher className={cn(facility && "text-white")} />
        <nav aria-label="Main" className="-mx-1 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-1">
          {items.map((item) => (
            <SidebarLink key={item.to} item={item} facility={facility} selected={item.to === current} />
          ))}
        </nav>
        {!signedIn && <div className="flex flex-col">{logIn}</div>}
      </aside>

      <div className="flex min-h-dvh min-w-0 flex-col">
        <header
          className={cn(
            "sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b px-4 backdrop-blur lg:hidden",
            facility ? "border-brand-navy bg-brand-navy text-white" : "bg-card/95",
          )}
        >
          <Wordmark className={cn(facility && "text-white [&>span]:text-brand-cyan")} />
          <div className="flex min-w-0 items-center gap-1">
            <OrganizationSwitcher className={cn("max-w-[55vw]", facility && "text-white")} />
            {signedIn ? <NotificationBell /> : logIn}
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 py-6 pb-28 lg:px-8 lg:pb-8">
          <UpdateBanner className="mb-6" />
          <OfflineBanner className="mb-6" />
          <Outlet />
        </main>

        <nav
          aria-label="Main"
          style={{ gridTemplateColumns: `repeat(${bar.length}, minmax(0, 1fr))` }}
          className={cn(
            "fixed inset-x-0 bottom-0 z-10 grid border-t pb-[env(safe-area-inset-bottom)] lg:hidden",
            facility ? "border-brand-navy bg-brand-navy" : "bg-card",
          )}
        >
          {bar.map((item) => (
            <TabLink key={item.to} item={item} facility={facility} selected={item.to === current || (item === MORE && more.some((m) => m.to === current))} />
          ))}
        </nav>
      </div>
    </div>
  )
}

/** The menu entry for this page: the longest `to` the path sits under, so /club/tournaments lights up
 * Tournaments and not Club as well. */
function currentEntry(pathname: string, entries: readonly NavItem[]): string | undefined {
  const under = entries.filter((e) => pathname === e.to || pathname.startsWith(`${e.to}/`))
  return under.sort((a, b) => b.to.length - a.to.length)[0]?.to
}

function TabLink({ item: { to, label, icon: Icon }, facility, selected }: { item: NavItem; facility: boolean; selected: boolean }) {
  return (
    <NavLink
      to={to}
      aria-current={selected ? "page" : undefined}
      className={() =>
        cn(
          "flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 px-0.5 text-xs font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50 sm:text-sm",
          facility ? "text-white/70" : "text-muted-foreground",
          selected && (facility ? "text-brand-gold" : "text-brand-blue"),
        )
      }
    >
      <Icon aria-hidden className="size-6 shrink-0" />
      <span className="max-w-full truncate">{label}</span>
    </NavLink>
  )
}

function SidebarLink({ item: { to, label, icon: Icon }, facility, selected }: { item: NavItem; facility: boolean; selected: boolean }) {
  return (
    <NavLink
      to={to}
      aria-current={selected ? "page" : undefined}
      className={() =>
        cn(
          "flex h-12 shrink-0 items-center gap-3 rounded-lg px-3 font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          facility ? "text-white/75 hover:bg-white/10 hover:text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground",
          selected && (facility ? "bg-white/15 text-white" : "bg-surface-selected text-brand-blue"),
        )
      }
    >
      <Icon aria-hidden className="size-5" />
      {label}
    </NavLink>
  )
}
