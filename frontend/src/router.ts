import { createRouter, createWebHistory } from 'vue-router'
import HomePage from './views/HomePage.vue'
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

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomePage },
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
  ],
})
