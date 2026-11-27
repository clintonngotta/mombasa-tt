// Who is signed in, checked again in the background (REQ-035). Only the server saying the session is
// over signs a person out here; losing the connection, a server error or a proxy page in the way
// doesn't. Those keep the account this device already knew, so the app goes on working offline.

/** The server answered that nobody is signed in: the session expired, was ended, or never was. */
export function sessionEnded(error: unknown): boolean {
  const status = typeof error === "object" && error !== null && "status" in error ? (error as { status: unknown }).status : undefined
  return status === 401 || status === 403
}

/** Ask who is signed in; if the answer can't be had, carry on as `known`, when there is one. */
export async function checkSession<U>(ask: () => Promise<U>, known: U | undefined): Promise<U> {
  try {
    return await ask()
  } catch (error) {
    if (known !== undefined && known !== null && !sessionEnded(error)) return known
    throw error
  }
}
