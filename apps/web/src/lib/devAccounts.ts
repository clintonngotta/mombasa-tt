export type DevAccount = { role: string; email: string; password: string }

const DEV_PASSWORD = import.meta.env.VITE_DEV_LOGIN_PASSWORD ?? "mombasa-tt-dev"

// Development-only test logins. `import.meta.env.DEV` is false in production builds,
// so the list (and these credentials) are stripped from the shipped bundle.
// The API's dev seed data must create matching users.
export const DEV_ACCOUNTS: DevAccount[] = import.meta.env.DEV
  ? [
      { role: "Player", email: import.meta.env.VITE_DEV_LOGIN_EMAIL ?? "player@mombasa-tt.test", password: DEV_PASSWORD },
      { role: "Umpire", email: "umpire@mombasa-tt.test", password: DEV_PASSWORD },
      { role: "Club admin", email: "admin@mombasa-tt.test", password: DEV_PASSWORD },
    ]
  : []
