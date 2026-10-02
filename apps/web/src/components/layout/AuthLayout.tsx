import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { Wordmark } from "@/components/brand/Wordmark"

type AuthLayoutProps = {
  title: string
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
}

export function AuthLayout({ title, description, children, footer }: AuthLayoutProps) {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="flex h-14 items-center px-4 sm:px-8">
        <Link to="/" className="rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <Wordmark />
        </Link>
      </header>
      <main className="mx-auto flex w-full max-w-[440px] flex-1 flex-col gap-6 px-4 pt-6 pb-10 sm:pt-12">
        <div className="flex flex-col gap-2">
          <h1 className="text-[32px] leading-9 font-bold">{title}</h1>
          {description && <p className="text-muted-foreground">{description}</p>}
        </div>
        {children}
        {footer && <div className="text-center text-muted-foreground">{footer}</div>}
      </main>
    </div>
  )
}
