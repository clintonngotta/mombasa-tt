import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

/** "← Somewhere" link at the top of a sub-page. */
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="-ml-1 flex w-fit items-center gap-1 py-2 font-semibold text-brand-blue">
      <ArrowLeft aria-hidden className="size-5" /> {children}
    </Link>
  )
}
