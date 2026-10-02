import { api } from "@/lib/api"

export type SignUpInput = { display_name: string; email: string; password: string }
export type LogInInput = { email: string; password: string }

export const signUp = (input: SignUpInput) => api<void>("/auth/signup/", { body: input })

export const logIn = (input: LogInInput) => api<void>("/auth/login/", { body: input })

// The API answers identically whether or not the address exists (REQ-003: no enumeration).
export const requestPasswordReset = (email: string) => api<void>("/auth/password-reset/", { body: { email } })

export const resendVerification = (email: string) => api<void>("/auth/verification/resend/", { body: { email } })

export const MIN_PASSWORD_LENGTH = 10
