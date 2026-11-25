import { QueryClientProvider } from "@tanstack/react-query"
import { queryClient } from "@/lib/queryClient"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { GalleryPage } from "@/pages/dev/GalleryPage"
import { WelcomePage } from "@/pages/auth/WelcomePage"
import { SignUpPage } from "@/pages/auth/SignUpPage"
import { CheckEmailPage } from "@/pages/auth/CheckEmailPage"
import { LogInPage } from "@/pages/auth/LogInPage"
import { JoinPage } from "@/pages/auth/JoinPage"
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
import { GuestClaimsPage } from "@/pages/profile/GuestClaimsPage"
import { ClubSessionsPage } from "@/pages/club/ClubSessionsPage"
import { ClubSessionPage } from "@/pages/club/ClubSessionPage"
import { FindFacilityPage } from "@/pages/facilities/FindFacilityPage"
import { FacilityPage } from "@/pages/facilities/FacilityPage"
import { DoorPage } from "@/pages/club/DoorPage"
import { TakingsPage } from "@/pages/club/TakingsPage"
import { MyVisitsPage } from "@/pages/profile/MyVisitsPage"
import { ActivitiesPage } from "@/pages/club/ActivitiesPage"
import { ActivityPage } from "@/pages/club/ActivityPage"
import { ClubSchedulePage } from "@/pages/club/ClubSchedulePage"
import { SodaGamesPage } from "@/pages/play/SodaGamesPage"
import { EventsPage } from "@/pages/events/EventsPage"
import { ClubEventsPage } from "@/pages/events/ClubEventsPage"
import { ReviewEventsPage } from "@/pages/events/ReviewEventsPage"
import { NotificationsPage } from "@/pages/NotificationsPage"
import { AnnouncePage } from "@/pages/club/AnnouncePage"
import { MyBookingsPage } from "@/pages/profile/MyBookingsPage"
import { ClubBookingsPage } from "@/pages/club/ClubBookingsPage"
import { ClubFinancePage } from "@/pages/club/ClubFinancePage"
import { CampaignsPage } from "@/pages/club/CampaignsPage"
import { SpendingPage } from "@/pages/club/SpendingPage"
import { WelfarePage } from "@/pages/club/WelfarePage"
import { MyFinancesPage } from "@/pages/club/MyFinancesPage"
import { GuestsPage } from "@/pages/club/GuestsPage"
import { PlayersPage } from "@/pages/players/PlayersPage"
import { PlayerPage } from "@/pages/players/PlayerPage"
import { PlayerRatingsPage } from "@/pages/ratings/PlayerRatingsPage"
import { RankingsPage } from "@/pages/ratings/RankingsPage"
import { ClubPage } from "@/pages/club/ClubPage"
import { FindClubPage } from "@/pages/club/FindClubPage"
import { RegisterOrganizationPage } from "@/pages/club/RegisterOrganizationPage"
import { InvitationsInboxPage } from "@/pages/club/InvitationsInboxPage"
import { AdminNominationsPage } from "@/pages/club/AdminNominationsPage"
import { MembersPage } from "@/pages/club/MembersPage"
import { ClubProfilePage } from "@/pages/club/ClubProfilePage"
import { ClubProfileEditPage } from "@/pages/club/ClubProfileEditPage"
import { TrainingPage } from "@/pages/training/TrainingPage"
import { CeremonyPage } from "@/pages/tournaments/CeremonyPage"
import { AnnouncementsPage } from "@/pages/tournaments/AnnouncementsPage"
import { LivePage } from "@/pages/tournaments/LivePage"
import { OrderOfPlayPage } from "@/pages/tournaments/OrderOfPlayPage"
import { ArticlePage, RegionPage } from "@/pages/region/RegionPage"
import { MeetingPage, MeetingsPage } from "@/pages/region/MeetingPages"
import { ClubPlanPage, PlanPage, TraineePlanPage } from "@/pages/training/PlanPage"
import { CoachesPage } from "@/pages/coaching/CoachesPage"
import { CoachPage } from "@/pages/coaching/CoachPage"
import { CoachProfilePage } from "@/pages/coaching/CoachProfilePage"
import { TraineePage } from "@/pages/coaching/TraineePage"
import { DrillDetailPage } from "@/pages/training/DrillDetailPage"
import { DrillEditPage } from "@/pages/training/DrillEditPage"
import { CommitteePage } from "@/pages/club/CommitteePage"
import { RepresentativesPage } from "@/pages/club/RepresentativesPage"
import { RolesPage } from "@/pages/club/RolesPage"
import { RoleEditPage } from "@/pages/club/RoleEditPage"
import { MemberFieldsPage } from "@/pages/club/MemberFieldsPage"
import { MemberFieldEditPage } from "@/pages/club/MemberFieldEditPage"
import { VenuesPage } from "@/pages/club/VenuesPage"
import { VenueEditPage } from "@/pages/club/VenueEditPage"
import { TournamentDashboardsPage } from "@/pages/club/TournamentDashboardsPage"
import { PlayPage } from "@/pages/tournaments/PlayPage"
import { TournamentPage } from "@/pages/tournaments/TournamentPage"
import { TournamentDashboardPage } from "@/pages/tournaments/TournamentDashboardPage"
import { TournamentFormPage } from "@/pages/tournaments/TournamentFormPage"
import { EventFormPage } from "@/pages/tournaments/EventFormPage"
import { EntriesPage } from "@/pages/tournaments/EntriesPage"
import { DrawPage } from "@/pages/tournaments/DrawPage"
import { EventPage } from "@/pages/tournaments/EventPage"
import { MatchPage } from "@/pages/tournaments/MatchPage"
import { ScoringOverviewPage } from "@/pages/tournaments/ScoringOverviewPage"
import { DispatchBoardPage } from "@/pages/tournaments/DispatchBoardPage"
import { SchedulePage } from "@/pages/tournaments/SchedulePage"
import { CorrectionsPage } from "@/pages/tournaments/CorrectionsPage"
import { ScoringDeckRoute } from "@/pages/scoring/ScoringDeckPage"
import { QuickScorePage } from "@/pages/play/QuickScorePage"
import { HomeRoute, PersonOnly } from "@/components/auth/PersonOnly"
import { FacilityHomePage } from "@/pages/facilities/FacilityHomePage"
import { CoachingPage } from "@/pages/coaching/CoachingPage"
import { RegionalPage } from "@/pages/region/RegionalPage"
import { MorePage } from "@/pages/MorePage"
import { SyncPage } from "@/pages/profile/SyncPage"
import { TournamentsPage } from "@/pages/tournaments/TournamentsPage"
import { HelpPage } from "@/pages/help/HelpPage"

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<WelcomePage />} />
          <Route path="/signup" element={<SignUpPage />} />
          <Route path="/signup/check-email" element={<CheckEmailPage />} />
          <Route path="/login" element={<LogInPage />} />
          {/* An invitation link: open signed out, the link itself is the proof (REQ-003). */}
          <Route path="/join/:token" element={<JoinPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/verify-email" element={<VerifyEmailPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/onboarding" element={<Navigate to="/onboarding/profile" replace />} />
          <Route path="/onboarding/profile" element={<ProfileSetupPage />} />
          <Route path="/onboarding/community" element={<FindCommunityPage />} />
          <Route path="/onboarding/goals" element={<GoalsPage />} />
          <Route path="/onboarding/complete" element={<CompletionPage />} />

          {/* The scoring deck is full screen, outside the app's navigation (REQ-002). */}
          {/* Quick Score is full screen too, and open to anyone: a guest can score without an account (REQ-017). */}
          <Route path="/quick-score" element={<QuickScorePage />} />
          <Route element={<RequireAuth />}>
            <Route path="/score/:id" element={<ScoringDeckRoute />} />
          </Route>

          <Route element={<AppShell />}>
            {/* Domain screens land here as their Stitch references are implemented. */}
            <Route path="/home" element={<HomeRoute />} />
            {/* The events listing is public (REQ-042). */}
            <Route path="/events" element={<EventsPage />} />
            {/* Published tournaments, their results, rankings and ratings are public (REQ-020, TASK-035). A
                facility acting as itself is still sent back to its desk from rankings (PersonOnly). */}
            <Route path="/tournaments" element={<TournamentsPage />} />
            {/* Help is for everyone, including someone deciding whether to sign up. */}
            <Route path="/help" element={<HelpPage />} />
            <Route path="/tournaments/:id" element={<TournamentPage />} />
            <Route path="/tournaments/:id/events/:eventId/entries" element={<EntriesPage />} />
            <Route path="/tournaments/:id/events/:eventId/brackets" element={<EventPage tab="brackets" />} />
            <Route path="/tournaments/:id/events/:eventId/groups" element={<EventPage tab="groups" />} />
            <Route path="/tournaments/:id/events/:eventId/schedule" element={<EventPage tab="schedule" />} />
            <Route path="/tournaments/:id/events/:eventId/standings" element={<EventPage tab="standings" />} />
            <Route path="/tournaments/:id/events/:eventId/matches/:matchId" element={<MatchPage />} />
            <Route path="/tournaments/:id/ceremony" element={<CeremonyPage />} />
            <Route path="/tournaments/:id/live" element={<LivePage />} />
            <Route path="/tournaments/:id/order-of-play" element={<OrderOfPlayPage />} />
            <Route path="/players/:id" element={<PlayerPage />} />
            <Route element={<PersonOnly />}>
              <Route path="/rankings" element={<RankingsPage />} />
              <Route path="/ratings/:id" element={<PlayerRatingsPage />} />
            </Route>
            <Route element={<RequireAuth />}>
              <Route path="/notifications" element={<NotificationsPage />} />
              <Route element={<PersonOnly />}>
                <Route path="/play" element={<PlayPage />} />
                <Route path="/play/soda" element={<SodaGamesPage />} />
                <Route path="/training" element={<TrainingPage />} />
                <Route path="/training/plans/:id" element={<PlanPage />} />
                <Route path="/training/club-plans/:id" element={<ClubPlanPage />} />
                <Route path="/coaches" element={<CoachesPage />} />
                <Route path="/coaches/:id" element={<CoachPage />} />
                <Route path="/coaching/profile" element={<CoachProfilePage />} />
                <Route path="/coaching/trainees/:id" element={<TraineePage />} />
                <Route path="/coaching/trainees/:coachingId/plans/:id" element={<TraineePlanPage />} />
                <Route path="/training/drills" element={<Navigate to="/training?tab=drills" replace />} />
                <Route path="/training/drills/new" element={<DrillEditPage />} />
                <Route path="/training/drills/:id" element={<DrillDetailPage />} />
                <Route path="/training/drills/:id/edit" element={<DrillEditPage />} />
                <Route path="/matches" element={<MatchLogPage />} />
                <Route path="/matches/new" element={<MatchFormPage />} />
                <Route path="/matches/:id" element={<MatchDetailPage />} />
                <Route path="/matches/:id/edit" element={<MatchFormPage />} />
                <Route path="/coaching" element={<CoachingPage />} />
              </Route>
              <Route path="/facility" element={<FacilityHomePage />} />
              <Route path="/regional" element={<RegionalPage />} />
              <Route path="/more" element={<MorePage />} />
              <Route path="/tournaments/:id/edit" element={<TournamentFormPage />} />
              <Route path="/tournaments/:id/dashboard" element={<TournamentDashboardPage />} />
              <Route path="/tournaments/:id/announcements" element={<AnnouncementsPage />} />
              <Route path="/tournaments/:id/scoring" element={<ScoringOverviewPage />} />
              <Route path="/tournaments/:id/dispatch" element={<DispatchBoardPage />} />
              <Route path="/tournaments/:id/schedule-plan" element={<SchedulePage />} />
              <Route path="/tournaments/:id/corrections" element={<CorrectionsPage />} />
              <Route path="/tournaments/:id/events/new" element={<EventFormPage />} />
              <Route path="/tournaments/:id/events/:eventId" element={<EventFormPage />} />
              <Route path="/tournaments/:id/events/:eventId/draw" element={<DrawPage />} />
              <Route path="/club/tournaments" element={<TournamentDashboardsPage />} />
              <Route path="/club/tournaments/new" element={<TournamentFormPage />} />
              <Route path="/club/venues" element={<VenuesPage />} />
              <Route path="/club/venues/new" element={<VenueEditPage />} />
              <Route path="/club/venues/:id" element={<VenueEditPage />} />
              <Route path="/club/venues/:id/door" element={<DoorPage />} />
              <Route path="/club/takings" element={<TakingsPage />} />
              <Route path="/club/bookings" element={<ClubBookingsPage />} />
              <Route path="/club/finance" element={<ClubFinancePage />} />
              <Route path="/club/finance/campaigns" element={<CampaignsPage />} />
              <Route path="/club/finance/spending" element={<SpendingPage />} />
              <Route path="/club/welfare" element={<WelfarePage />} />
              <Route path="/club/my-payments" element={<MyFinancesPage />} />
              <Route path="/club" element={<ClubPage />} />
              <Route path="/club/find" element={<FindClubPage />} />
              <Route path="/club/find/:id" element={<ClubProfilePage />} />
              <Route path="/club/profile" element={<ClubProfileEditPage />} />
              <Route path="/club/new" element={<RegisterOrganizationPage />} />
              <Route path="/club/invitations" element={<InvitationsInboxPage />} />
              <Route path="/club/admin-nominations" element={<AdminNominationsPage />} />
              <Route path="/club/members" element={<MembersPage />} />
              <Route path="/club/guests" element={<GuestsPage />} />
              <Route path="/club/sessions" element={<ClubSessionsPage />} />
              <Route path="/club/sessions/:id" element={<ClubSessionPage />} />
              <Route path="/club/activities" element={<ActivitiesPage />} />
              <Route path="/club/announce" element={<AnnouncePage />} />
              <Route path="/club/external-events" element={<ClubEventsPage />} />
              <Route path="/events/review" element={<ReviewEventsPage />} />
              <Route path="/club/schedule" element={<ClubSchedulePage />} />
              <Route path="/activities/:orgId/:id" element={<ActivityPage />} />
              <Route path="/facilities" element={<FindFacilityPage />} />
              <Route path="/facilities/:id" element={<FacilityPage />} />
              <Route path="/club/committee" element={<CommitteePage />} />
              <Route path="/club/representatives" element={<RepresentativesPage />} />
              <Route path="/club/roles" element={<RolesPage />} />
              <Route path="/club/roles/new" element={<RoleEditPage />} />
              <Route path="/club/roles/:id" element={<RoleEditPage />} />
              <Route path="/club/fields" element={<MemberFieldsPage />} />
              <Route path="/club/fields/new" element={<MemberFieldEditPage />} />
              <Route path="/club/fields/:id" element={<MemberFieldEditPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/profile/edit" element={<ProfileEditPage />} />
              <Route path="/profile/sync" element={<SyncPage />} />
              <Route path="/profile/claims" element={<GuestClaimsPage />} />
              <Route path="/profile/visits" element={<MyVisitsPage />} />
              <Route path="/profile/bookings" element={<MyBookingsPage />} />
              <Route path="/region" element={<RegionPage />} />
              <Route path="/news/:orgId/:id" element={<ArticlePage />} />
              <Route path="/club/meetings" element={<MeetingsPage />} />
              <Route path="/meetings/:orgId/:id" element={<MeetingPage />} />
              <Route path="/players" element={<PlayersPage />} />
            </Route>
            {import.meta.env.DEV && <Route path="/dev/gallery" element={<GalleryPage />} />}
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
