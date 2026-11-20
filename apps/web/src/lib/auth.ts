import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type SignUpInput = Schemas["SignUpRequest"]
export type LogInInput = { email: string; password: string }

export const signUp = (input: SignUpInput) => api<void>("/auth/signup/", { body: input })

export const logIn = (input: LogInInput) => api<User>("/auth/login/", { body: input })

// The API answers identically whether or not the address exists (REQ-003: no enumeration).
export const requestPasswordReset = (email: string) => api<void>("/auth/password-reset/", { body: { email } })

export type User = Schemas["User"]

export const verifyEmail = (token: string) => api<User>("/auth/verification/confirm/", { body: { token } })

export const confirmPasswordReset = (input: { uid: string; token: string; password: string }) =>
  api<void>("/auth/password-reset/confirm/", { body: input })

export const logOut = () => api<void>("/auth/logout/", { body: {} })

export const resendVerification = (email: string) => api<void>("/auth/verification/resend/", { body: { email } })

export const MIN_PASSWORD_LENGTH = 10
