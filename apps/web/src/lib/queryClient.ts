import { QueryClient } from "@tanstack/react-query"

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      // Screens stay in memory for a day so they can be saved on the device and shown offline (lib/offline).
      gcTime: 24 * 60 * 60 * 1000,
      retry: 1,
    },
  },
})
