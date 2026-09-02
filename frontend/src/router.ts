import { createRouter, createWebHistory } from 'vue-router'
import HomePage from './views/HomePage.vue'
import AuthLandingPage from './views/AuthLandingPage.vue'
import PlannerPage from './views/PlannerPage.vue'
import ItinerariesPage from './views/ItinerariesPage.vue'
import AdminPage from './views/AdminPage.vue'
import AdminAttractionsPage from './views/AdminAttractionsPage.vue'
import AdminCitiesPage from './views/AdminCitiesPage.vue'
import AdminSessionsPage from './views/AdminSessionsPage.vue'
import AdminUsersPage from './views/AdminUsersPage.vue'
import ProfileSettingsPage from './views/ProfileSettingsPage.vue'
import CityDetailPage from './views/CityDetailPage.vue'
import CityList from './views/CityList.vue'
import AttractionDetailPage from './views/AttractionDetailPage.vue'
import RankingsPage from './views/RankingsPage.vue'
import UserHomePage from './views/UserHomePage.vue'
import SecuritySettingsPage from './views/SecuritySettingsPage.vue'
import ItineraryDetailPage from './views/ItineraryDetailPage.vue'
import ShareItineraryPage from './views/ShareItineraryPage.vue'
import AdminFeedbackPage from './views/AdminFeedbackPage.vue'
import AdminMediaAssetsPage from './views/AdminMediaAssetsPage.vue'
import AdminRankingsPage from './views/AdminRankingsPage.vue'
import AdminAuditLogsPage from './views/AdminAuditLogsPage.vue'
import CommunityPage from './views/CommunityPage.vue'
import CommunityDetailPage from './views/CommunityDetailPage.vue'
import CommunityPublishPage from './views/CommunityPublishPage.vue'
import AdminCommunityPage from './views/AdminCommunityPage.vue'
import AdminItinerariesPage from './views/AdminItinerariesPage.vue'
import AuthActionPage from './views/AuthActionPage.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'entry', component: AuthLandingPage },
    { path: '/auth/verify-email', name: 'auth-verify', component: AuthActionPage },
    { path: '/auth/resend-verification', name: 'auth-resend', component: AuthActionPage },
    { path: '/auth/forgot-password', name: 'auth-forgot', component: AuthActionPage },
    { path: '/auth/reset-password', name: 'auth-reset', component: AuthActionPage },
    { path: '/auth/confirm-email-change', name: 'auth-change-confirm', component: AuthActionPage },
    { path: '/discover', name: 'discover', component: HomePage },
    { path: '/community', component: CommunityPage },
    { path: '/community/publish', component: CommunityPublishPage },
    { path: '/community/posts/:id', component: CommunityDetailPage },
    { path: '/planner', component: PlannerPage },
    { path: '/itineraries', component: ItinerariesPage },
    { path: '/itineraries/:id', component: ItineraryDetailPage },
    { path: '/rankings', component: RankingsPage },
    { path: '/cities', component: CityList },
    { path: '/cities/:slug', component: CityDetailPage },
    { path: '/attractions/:id', component: AttractionDetailPage },
    { path: '/me', component: UserHomePage },
    { path: '/me/settings/profile', component: ProfileSettingsPage },
    { path: '/me/settings/security', component: SecuritySettingsPage },
    { path: '/share/itineraries/:token', component: ShareItineraryPage },
    { path: '/admin', component: AdminPage },
    { path: '/admin/cities', component: AdminCitiesPage },
    { path: '/admin/attractions', component: AdminAttractionsPage },
    { path: '/admin/users', component: AdminUsersPage },
    { path: '/admin/sessions', component: AdminSessionsPage },
    { path: '/admin/feedback', component: AdminFeedbackPage },
    { path: '/admin/media-assets', component: AdminMediaAssetsPage },
    { path: '/admin/rankings', component: AdminRankingsPage },
    { path: '/admin/audit-logs', component: AdminAuditLogsPage },
    { path: '/admin/community', component: AdminCommunityPage },
    { path: '/admin/itineraries', component: AdminItinerariesPage },
  ],
})
