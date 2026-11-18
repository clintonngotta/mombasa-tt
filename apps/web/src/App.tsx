import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { GalleryPage } from "@/pages/dev/GalleryPage"
import { WelcomePage } from "@/pages/auth/WelcomePage"
import { SignUpPage } from "@/pages/auth/SignUpPage"
import { CheckEmailPage } from "@/pages/auth/CheckEmailPage"
import { LogInPage } from "@/pages/auth/LogInPage"
import { ForgotPasswordPage } from "@/pages/auth/ForgotPasswordPage"
import { VerifyEmailPage } from "@/pages/auth/VerifyEmailPage"
import { ResetPasswordPage } from "@/pages/auth/ResetPasswordPage"
import { ProfileSetupPage } from "@/pages/onboarding/ProfileSetupPage"
import { FindCommunityPage } from "@/pages/onboarding/FindCommunityPage"
import { GoalsPage } from "@/pages/onboarding/GoalsPage"
import { CompletionPage } from "@/pages/onboarding/CompletionPage"
import { RequireAuth } from "@/components/auth/RequireAuth"
import { MatchLogPage } from "@/pages/matches/MatchLogPage"
import { MatchFormPage } from "@/pages/matches/MatchFormPage"
import { MatchDetailPage } from "@/pages/matches/MatchDetailPage"
import { ProfilePage } from "@/pages/profile/ProfilePage"
import { ProfileEditPage } from "@/pages/profile/ProfileEditPage"
import { PlayersPage } from "@/pages/players/PlayersPage"
import { PlayerPage } from "@/pages/players/PlayerPage"
import { ClubPage } from "@/pages/club/ClubPage"
import { FindClubPage } from "@/pages/club/FindClubPage"
import { RegisterOrganizationPage } from "@/pages/club/RegisterOrganizationPage"
import { InvitationsInboxPage } from "@/pages/club/InvitationsInboxPage"
import { MembersPage } from "@/pages/club/MembersPage"
import { RolesPage } from "@/pages/club/RolesPage"
import { RoleEditPage } from "@/pages/club/RoleEditPage"
import { MemberFieldsPage } from "@/pages/club/MemberFieldsPage"
import { MemberFieldEditPage } from "@/pages/club/MemberFieldEditPage"
import { VenuesPage } from "@/pages/club/VenuesPage"
import { VenueEditPage } from "@/pages/club/VenueEditPage"
import { HostedTournamentsPage } from "@/pages/club/HostedTournamentsPage"
import { PlayPage } from "@/pages/tournaments/PlayPage"
import { TournamentPage } from "@/pages/tournaments/TournamentPage"
import { TournamentFormPage } from "@/pages/tournaments/TournamentFormPage"
import { EventFormPage } from "@/pages/tournaments/EventFormPage"
import { EntriesPage } from "@/pages/tournaments/EntriesPage"
import { DrawPage } from "@/pages/tournaments/DrawPage"
import { EventPage } from "@/pages/tournaments/EventPage"
import { MatchPage } from "@/pages/tournaments/MatchPage"
import { ScoringOverviewPage } from "@/pages/tournaments/ScoringOverviewPage"
import { ScoringDeckRoute } from "@/pages/scoring/ScoringDeckPage"

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
          <Route path="/signup/check-email" element={<CheckEmailPage />} />
          <Route path="/login" element={<LogInPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/onboarding" element={<Navigate to="/onboarding/profile" replace />} />
          <Route path="/onboarding/profile" element={<ProfileSetupPage />} />
          <Route path="/onboarding/community" element={<FindCommunityPage />} />
          <Route path="/onboarding/goals" element={<GoalsPage />} />
          <Route path="/onboarding/complete" element={<CompletionPage />} />

          {/* The scoring deck is full screen, outside the app's navigation (REQ-002). */}
          <Route element={<RequireAuth />}>
            <Route path="/score/:id" element={<ScoringDeckRoute />} />
          </Route>

          <Route element={<AppShell />}>
            {/* Domain screens land here as their Stitch references are implemented. */}
            <Route path="/home" element={null} />
            <Route element={<RequireAuth />}>
              <Route path="/play" element={<PlayPage />} />
              <Route path="/tournaments/:id" element={<TournamentPage />} />
              <Route path="/tournaments/:id/edit" element={<TournamentFormPage />} />
              <Route path="/tournaments/:id/scoring" element={<ScoringOverviewPage />} />
              <Route path="/tournaments/:id/events/new" element={<EventFormPage />} />
              <Route path="/tournaments/:id/events/:eventId" element={<EventFormPage />} />
              <Route path="/tournaments/:id/events/:eventId/entries" element={<EntriesPage />} />
              <Route path="/tournaments/:id/events/:eventId/draw" element={<DrawPage />} />
              <Route path="/tournaments/:id/events/:eventId/brackets" element={<EventPage tab="brackets" />} />
              <Route path="/tournaments/:id/events/:eventId/groups" element={<EventPage tab="groups" />} />
              <Route path="/tournaments/:id/events/:eventId/schedule" element={<EventPage tab="schedule" />} />
              <Route path="/tournaments/:id/events/:eventId/standings" element={<EventPage tab="standings" />} />
              <Route path="/tournaments/:id/events/:eventId/matches/:matchId" element={<MatchPage />} />
              <Route path="/club/tournaments" element={<HostedTournamentsPage />} />
              <Route path="/club/tournaments/new" element={<TournamentFormPage />} />
              <Route path="/club/venues" element={<VenuesPage />} />
              <Route path="/club/venues/new" element={<VenueEditPage />} />
              <Route path="/club/venues/:id" element={<VenueEditPage />} />
              <Route path="/club" element={<ClubPage />} />
              <Route path="/club/find" element={<FindClubPage />} />
              <Route path="/club/new" element={<RegisterOrganizationPage />} />
              <Route path="/club/invitations" element={<InvitationsInboxPage />} />
              <Route path="/club/members" element={<MembersPage />} />
              <Route path="/club/roles" element={<RolesPage />} />
              <Route path="/club/roles/new" element={<RoleEditPage />} />
              <Route path="/club/roles/:id" element={<RoleEditPage />} />
              <Route path="/club/fields" element={<MemberFieldsPage />} />
              <Route path="/club/fields/new" element={<MemberFieldEditPage />} />
              <Route path="/club/fields/:id" element={<MemberFieldEditPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/profile/edit" element={<ProfileEditPage />} />
              <Route path="/players" element={<PlayersPage />} />
              <Route path="/players/:id" element={<PlayerPage />} />
              <Route path="/matches" element={<MatchLogPage />} />
              <Route path="/matches/new" element={<MatchFormPage />} />
              <Route path="/matches/:id" element={<MatchDetailPage />} />
              <Route path="/matches/:id/edit" element={<MatchFormPage />} />
            </Route>
            {import.meta.env.DEV && <Route path="/dev/gallery" element={<GalleryPage />} />}
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
