import { NavLink, Outlet } from "react-router-dom"
import { Dumbbell, House, Swords, Trophy, Users, UserRound, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Wordmark } from "@/components/brand/Wordmark"
import { OrganizationSwitcher } from "@/components/clubs/OrganizationSwitcher"

type NavItem = { to: string; label: string; icon: LucideIcon }

// REQ-002: mobile tabs and the web sidebar share the same domain names.
const NAV_ITEMS: NavItem[] = [
  { to: "/home", label: "Home", icon: House },
  { to: "/play", label: "Play", icon: Swords },
  { to: "/training", label: "Training", icon: Dumbbell },
  { to: "/rankings", label: "Rankings", icon: Trophy },
  { to: "/club", label: "Club", icon: Users },
  { to: "/profile", label: "Profile", icon: UserRound },
]

export function AppShell() {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[240px_1fr]">
      <aside className="hidden border-r bg-card lg:flex lg:flex-col lg:gap-6 lg:p-4">
        <Wordmark className="px-3 pt-2" />
        <OrganizationSwitcher />
        <nav aria-label="Main" className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}
        </nav>
      </aside>

      <div className="flex min-h-dvh flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b bg-card/95 px-4 backdrop-blur lg:hidden">
          <Wordmark />
          <OrganizationSwitcher className="max-w-[55%]" />
        </header>

        <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 py-6 pb-24 lg:px-8 lg:pb-8">
          <Outlet />
        </main>

        <nav
          aria-label="Main"
          className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-6 border-t bg-card pb-[env(safe-area-inset-bottom)] lg:hidden"
        >
          {NAV_ITEMS.map((item) => (
            <TabLink key={item.to} item={item} />
          ))}
        </nav>
      </div>
    </div>
  )
}

function TabLink({ item: { to, label, icon: Icon } }: { item: NavItem }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "flex min-h-16 flex-col items-center justify-center gap-1 text-sm font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          isActive && "text-brand-blue"
        )
      }
    >
      <Icon aria-hidden className="size-6" />
      {label}
    </NavLink>
  )
}

function SidebarLink({ item: { to, label, icon: Icon } }: { item: NavItem }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "flex h-12 items-center gap-3 rounded-lg px-3 font-semibold text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
          isActive && "bg-surface-selected text-brand-blue"
        )
      }
    >
      <Icon aria-hidden className="size-5" />
      {label}
    </NavLink>
  )
}
