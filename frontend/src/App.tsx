import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './context/AuthContext'
import { ProtectedRoute, AdminRoute } from './components/ProtectedRoute'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Home } from './pages/Home'
import { Assistant } from './pages/Assistant'
import { Pace } from './pages/Pace'
import { Runs } from './pages/Runs'
import { RunDetail } from './pages/RunDetail'
import { Clients } from './pages/Clients'
import { ClientForm } from './pages/ClientForm'
import { ClientWorkspace } from './pages/ClientWorkspace'
import { ClientContent } from './pages/ClientContent'
import { BrandVoice } from './pages/BrandVoice'
import { Icp } from './pages/Icp'
import { InternalLinks } from './pages/InternalLinks'
import { LocalSeoContent } from './pages/LocalSeoContent'
import { ContentScheduler } from './pages/ContentScheduler'
import { ServicePages } from './pages/ServicePages'
import { LocationPages } from './pages/LocationPages'
import { Rankings } from './pages/Rankings'
import { ActionPlan } from './pages/ActionPlan'
import { CampaignGoals } from './pages/CampaignGoals'
import { Backlinks } from './pages/Backlinks'
import { Competitors } from './pages/Competitors'
import { DomainIntel } from './pages/DomainIntel'
import { Forecast } from './pages/Forecast'
import { Sops } from './pages/Sops'
import { Guides } from './pages/Guides'
import { AsanaTasks } from './pages/AsanaTasks'
import { Tasks } from './pages/Tasks'
import { MyTasks } from './pages/MyTasks'
import { TeamWorkload } from './pages/TeamWorkload'
import { TaskLibrary } from './pages/TaskLibrary'
import { ClientReports } from './pages/ClientReports'
import { GscResearch } from './pages/GscResearch'
import { LeadOff } from './pages/LeadOff'
import { Syndication } from './pages/Syndication'
import { Citations } from './pages/Citations'
import { TaskPlan } from './pages/TaskPlan'
import { AiVisibility } from './pages/AiVisibility'
import { MapsGeogrid } from './pages/MapsGeogrid'
import { MapsReport } from './pages/MapsReport'
import { RankReport } from './pages/RankReport'
import { Articles } from './pages/Articles'
import { Silos } from './pages/Silos'
import { Team } from './pages/Team'
import { SetPassword } from './pages/SetPassword'
import FanoutApp from './fanout/FanoutApp'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/set-password" element={<SetPassword />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<Home />} />
                      <Route path="/assistant" element={<Assistant />} />
                      <Route path="/pace" element={<Pace />} />
                      <Route path="/backlinks" element={<Backlinks />} />
                      {/* Topic Fan-out, merged in (Option C) — a native route
                          subtree that renders inside the suite Layout, so it
                          shares the suite sidebar. */}
                      <Route path="/fanout/*" element={<FanoutApp />} />
                      <Route path="/leadoff" element={<LeadOff />} />
                      <Route path="/runs" element={<Runs />} />
                      <Route path="/runs/:id" element={<RunDetail />} />
                      <Route path="/clients" element={<Clients />} />
                      <Route path="/clients/new" element={<AdminRoute><ClientForm /></AdminRoute>} />
                      <Route path="/clients/:id" element={<ClientWorkspace />} />
                      <Route path="/clients/:id/brand-voice" element={<BrandVoice />} />
                      <Route path="/clients/:id/icp" element={<Icp />} />
                      <Route path="/clients/:id/content" element={<ClientContent />} />
                      <Route path="/clients/:id/local-seo" element={<LocalSeoContent />} />
                      <Route path="/clients/:id/content-scheduler" element={<ContentScheduler />} />
                      <Route path="/clients/:id/service-pages" element={<ServicePages />} />
                      <Route path="/clients/:id/location-pages" element={<LocationPages />} />
                      <Route path="/clients/:id/rankings" element={<Rankings />} />
                      <Route path="/clients/:id/internal-links" element={<InternalLinks />} />
                      <Route path="/clients/:id/gsc-research" element={<GscResearch />} />
                      <Route path="/clients/:id/syndication" element={<Syndication />} />
                      <Route path="/clients/:id/citations" element={<Citations />} />
                      <Route path="/clients/:id/task-plan" element={<TaskPlan />} />
                      <Route path="/clients/:id/action-plan" element={<ActionPlan />} />
                      <Route path="/clients/:id/goals" element={<CampaignGoals />} />
                      <Route path="/clients/:id/competitors" element={<Competitors />} />
                      <Route path="/clients/:id/backlinks" element={<Backlinks />} />
                      <Route path="/clients/:id/domain-intel" element={<DomainIntel />} />
                      <Route path="/clients/:id/forecast" element={<Forecast />} />
                      <Route path="/clients/:id/sops" element={<Sops />} />
                      <Route path="/clients/:id/asana-tasks" element={<AsanaTasks />} />
                      <Route path="/clients/:id/tasks" element={<Tasks />} />
                      <Route path="/clients/:id/reports" element={<ClientReports />} />
                      <Route path="/clients/:id/ai-visibility" element={<AiVisibility />} />
                      <Route path="/clients/:id/maps" element={<MapsGeogrid />} />
                      <Route path="/clients/:id/maps/report" element={<MapsReport />} />
                      <Route path="/clients/:id/rankings/report" element={<RankReport />} />
                      <Route path="/clients/:id/rankings/report/:reportId" element={<RankReport />} />
                      <Route path="/clients/:id/edit" element={<AdminRoute><ClientForm /></AdminRoute>} />
                      <Route path="/articles" element={<Articles />} />
                      <Route path="/silos" element={<Silos />} />
                      <Route path="/my-tasks" element={<MyTasks />} />
                      <Route path="/workload" element={<TeamWorkload />} />
                      <Route path="/asana/task-library" element={<TaskLibrary />} />
                      <Route path="/playbook" element={<Sops />} />
                      <Route path="/guides" element={<Guides />} />
                      <Route path="/guides/:slug" element={<Guides />} />
                      <Route path="/team" element={<AdminRoute><Team /></AdminRoute>} />
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
