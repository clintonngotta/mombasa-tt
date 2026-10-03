import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { GalleryPage } from "@/pages/dev/GalleryPage"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Navigate to="/home" replace />} />
            {/* Domain screens land here as their Stitch references are implemented. */}
            <Route path="/home" element={null} />
            <Route path="/play" element={null} />
            <Route path="/club" element={null} />
            <Route path="/profile" element={null} />
            {import.meta.env.DEV && <Route path="/dev/gallery" element={<GalleryPage />} />}
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
