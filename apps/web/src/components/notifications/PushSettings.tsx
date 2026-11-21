import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { isAppleMobile } from "@/lib/pwa"
import { blocker, currentSubscription, disablePush, enablePush, getPushStatus, permission, pushKeys, removePushDevice, type PushStatus } from "@/lib/push"

const when = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })

/**
 * Push on this device (REQ-019, TASK-034): what the browser supports, switching it on and off, how to
 * unblock it, and the player's other devices. Whatever happens here, the inbox above has every alert.
 */
export function PushSettings() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: pushKeys.status, queryFn: getPushStatus, staleTime: 0 })
  const [here, setHere] = useState<string | null | undefined>(undefined) // this browser's endpoint
  const [allowed, setAllowed] = useState(permission())
  const [note, setNote] = useState<string | null>(null)
  const why = blocker()

  useEffect(() => {
    void currentSubscription().then((found) => setHere(found?.endpoint ?? null), () => setHere(null))
  }, [])

  const keep = (fresh: PushStatus | null) => {
    if (fresh) queryClient.setQueryData(pushKeys.status, fresh)
    else void queryClient.invalidateQueries({ queryKey: pushKeys.status })
  }
  const turnOn = useMutation({
    mutationFn: () => enablePush(status.data?.public_key ?? ""),
    onSuccess: async (result) => {
      setAllowed(permission())
      if ("status" in result) {
        keep(result.status)
        setHere((await currentSubscription())?.endpoint ?? null)
        setNote("Push is on for this device.")
      } else if (result.refused === "dismissed") setNote("Nothing changed. Tap Switch on again and choose Allow.")
      else if (result.refused === "unavailable") setNote("This browser can't show push messages here: the app's background worker isn't running (a private window, or a development build). Your inbox has every alert.")
    },
  })
  const turnOff = useMutation({
    mutationFn: disablePush,
    onSuccess: (fresh) => {
      keep(fresh)
      setHere(null)
      setNote("Push is off for this device. Your inbox still gets everything.")
    },
  })
  const remove = useMutation({ mutationFn: removePushDevice, onSuccess: keep })

  const test = async () => {
    const found = await navigator.serviceWorker.getRegistration("/")
    await found?.showNotification("Coast TT", { body: "Push messages show like this on this device.", icon: "/icons/icon-192.png", tag: "push-test" })
  }

  const devices = status.data?.devices ?? []
  const on = here != null && allowed === "granted"

  return (
    <section aria-labelledby="push-heading" className="flex flex-col gap-3 border-t pt-6">
      <h2 id="push-heading" className="text-xl font-bold">
        Push on this device
      </h2>
      <p className="text-sm text-muted-foreground">Optional. Alerts can also show on this device's lock screen while the app is closed. Your inbox keeps every alert either way.</p>
      {status.isError && <FormAlert>{errorMessage(status.error, "We couldn't check push for your account.")}</FormAlert>}
      {status.data && !status.data.configured ? (
        <p className="text-sm">Push messages aren't switched on for Coast TT yet. Your inbox has every alert.</p>
      ) : why ? (
        <Guidance why={why} />
      ) : allowed === "denied" ? (
        <Blocked />
      ) : (
        status.data && (
          <div className="flex flex-wrap items-center gap-2">
            {on ? (
              <>
                <span className="text-sm font-semibold">On for this device</span>
                <Button variant="outline" onClick={() => void test()}>
                  Show a test message
                </Button>
                <Button variant="ghost" disabled={turnOff.isPending} onClick={() => turnOff.mutate()}>
                  Switch off
                </Button>
              </>
            ) : (
              <Button disabled={turnOn.isPending || here === undefined} onClick={() => turnOn.mutate()}>
                Switch on for this device
              </Button>
            )}
          </div>
        )
      )}
      {note && (
        <p role="status" className="text-sm">
          {note}
        </p>
      )}
      {(turnOn.isError || turnOff.isError || remove.isError) && <FormAlert>{errorMessage(turnOn.error ?? turnOff.error ?? remove.error)}</FormAlert>}
      {devices.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="font-semibold">Devices that get your alerts</h3>
          <ul className="flex flex-col gap-1">
            {devices.map((device) => (
              <li key={device.id} className="flex min-h-12 items-center justify-between gap-3 rounded-xl border px-4">
                <span className="text-sm">
                  <span className="font-medium">{device.label || "A browser"}</span>
                  <span className="text-muted-foreground"> · added {when(device.created_at)}{device.last_sent_at ? ` · last alert ${when(device.last_sent_at)}` : ""}</span>
                </span>
                <Button variant="ghost" size="sm" disabled={remove.isPending} onClick={() => remove.mutate(device.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function Guidance({ why }: { why: NonNullable<ReturnType<typeof blocker>> }) {
  if (why === "install")
    return (
      <div className="flex flex-col gap-1 text-sm">
        <p>On iPhone and iPad, push works only in the app added to your Home Screen (iOS 16.4 or later):</p>
        <ol className="list-decimal pl-5">
          <li>In Safari, tap Share, then Add to Home Screen.</li>
          <li>Open Coast TT from the Home Screen and sign in.</li>
          <li>Come back to Notifications and switch push on.</li>
        </ol>
      </div>
    )
  if (why === "insecure") return <p className="text-sm">Push needs a secure (https) connection. Open Coast TT at its https address.</p>
  return <p className="text-sm">This browser can't show push messages here (a private window, or an older browser). Your inbox has every alert. Chrome, Edge, Firefox and Samsung Internet support push.</p>
}

function Blocked() {
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p>Notifications are blocked for Coast TT in this browser. To allow them:</p>
      <ul className="list-disc pl-5">
        {isAppleMobile() ? (
          <li>iPhone and iPad: Settings, Notifications, Coast TT, then Allow Notifications.</li>
        ) : (
          <>
            <li>Android (Chrome): tap the icon left of the address, then Permissions, Notifications, Allow.</li>
            <li>Computer: click the icon left of the address, then set Notifications to Allow.</li>
          </>
        )}
      </ul>
      <p>Then reload this page and switch push on.</p>
    </div>
  )
}
