import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Route, Routes } from "react-router-dom"
import { WelcomePage } from "@/pages/auth/WelcomePage"
import { SignUpPage } from "@/pages/auth/SignUpPage"
import { LogInPage } from "@/pages/auth/LogInPage"
import { ForgotPasswordPage } from "@/pages/auth/ForgotPasswordPage"
import { ProfileSetupPage } from "@/pages/onboarding/ProfileSetupPage"
import { FindCommunityPage } from "@/pages/onboarding/FindCommunityPage"
import { GoalsPage } from "@/pages/onboarding/GoalsPage"
import { CompletionPage } from "@/pages/onboarding/CompletionPage"

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
          <Route path="/" element={<WelcomePage />} />
          <Route path="/signup" element={<SignUpPage />} />
          <Route path="/login" element={<LogInPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/onboarding/profile" element={<ProfileSetupPage />} />
          <Route path="/onboarding/community" element={<FindCommunityPage />} />
          <Route path="/onboarding/goals" element={<GoalsPage />} />
          <Route path="/onboarding/complete" element={<CompletionPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
