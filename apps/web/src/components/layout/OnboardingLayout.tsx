import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { ArrowLeft } from "lucide-react"
import { Wordmark } from "@/components/brand/Wordmark"

const ONBOARDING_STEPS = ["Profile", "Community", "Goals"] as const

type OnboardingLayoutProps = {
  step: number
  title: string
  description: ReactNode
  backTo?: string
  children: ReactNode
}

export function OnboardingLayout({ step, title, description, backTo, children }: OnboardingLayoutProps) {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <header className="flex h-14 items-center justify-between gap-3 px-4 sm:px-8">
        {backTo ? (
          <Link
            to={backTo}
            className="-ml-3 flex size-12 items-center justify-center rounded-lg text-brand-navy outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <ArrowLeft aria-hidden className="size-6" />
            <span className="sr-only">Back</span>
          </Link>
        ) : (
          <Wordmark />
        )}
        <p className="text-sm font-semibold text-muted-foreground">
          Step {step} of {ONBOARDING_STEPS.length}
        </p>
      </header>

      <div className="mx-auto w-full max-w-[640px] px-4">
        <ol aria-label="Onboarding progress" className="grid grid-cols-3 gap-2">
          {ONBOARDING_STEPS.map((name, i) => (
            <li key={name} className="flex flex-col gap-1.5">
              <span
                aria-hidden
                className={i < step ? "h-1.5 rounded-full bg-brand-blue" : "h-1.5 rounded-full bg-border"}
              />
              <span className={i + 1 === step ? "text-sm font-semibold" : "text-sm text-muted-foreground"}>
                {name}
                {i + 1 < step && <span className="sr-only"> (done)</span>}
                {i + 1 === step && <span className="sr-only"> (current)</span>}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <main className="mx-auto flex w-full max-w-[640px] flex-1 flex-col gap-6 px-4 pt-6 pb-10">
        <div className="flex flex-col gap-2">
          <h1 className="text-[32px] leading-9 font-bold">{title}</h1>
          <p className="text-muted-foreground">{description}</p>
        </div>
        {children}
      </main>
    </div>
  )
}
