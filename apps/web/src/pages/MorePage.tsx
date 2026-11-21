import { Bell } from "lucide-react"
import { OrgLinkRow } from "@/components/clubs/OrganizationLinks"
import { useNavigation } from "@/lib/navigation"

/** The rest of the menu on a phone: whatever the bottom bar has no room for. */
export function MorePage() {
  const { items, more } = useNavigation()
  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <h1 className="text-[32px] leading-9 font-bold">More</h1>
      <nav aria-label="More" className="flex flex-col gap-2">
        {(more.length ? more : items).map(({ to, label, icon: Icon }) => (
          <OrgLinkRow key={to} to={to} icon={<Icon aria-hidden className="size-5 text-brand-blue" />}>
            {label}
          </OrgLinkRow>
        ))}
        <OrgLinkRow to="/notifications" icon={<Bell aria-hidden className="size-5 text-brand-blue" />}>
          Notifications
        </OrgLinkRow>
      </nav>
    </div>
  )
}
