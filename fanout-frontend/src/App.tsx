import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "./shared/auth";
import { Login } from "./shared/Login";
import { getMe } from "./shared/api";
import { SessionsPage } from "./owner/SessionsPage";
import { ApprovalsPage } from "./owner/ApprovalsPage";
import { NewSession } from "./owner/NewSession";
import { SessionWorkspace } from "./owner/SessionWorkspace";
import { DebugView } from "./owner/DebugView";
import { TableView } from "./owner/views/TableView";
import { ClusterView } from "./owner/views/ClusterView";
import { ArchitectureView } from "./owner/views/ArchitectureView";
import { SplitView } from "./owner/views/SplitView";
import { ExportsView } from "./owner/views/ExportsView";
import { ScheduleView } from "./owner/views/ScheduleView";
import { ArticlesView } from "./owner/views/ArticlesView";
import { Wizard } from "./va/Wizard";

// Role-gated app (PRD §11.1). Owners get the full §9 Owner UI; VAs get the §10
// linear wizard and a restricted results view — they can't reach Owner-mode
// routes (split view, project browser). Backend role checks back this up (§10.3).
export default function App() {
  const { session, loading } = useAuth();

  if (loading) return <div className="state-center">Loading…</div>;
  if (!session) return <Login />;

  return (
    <BrowserRouter basename="/fanout">
      <RoleRoutes />
    </BrowserRouter>
  );
}

function RoleRoutes() {
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });

  if (me.isLoading) return <div className="state-center">Loading…</div>;
  // On a transient /me failure, fall back to the more-restricted VA surface
  // rather than exposing Owner views.
  return me.data?.role === "owner" ? <OwnerRoutes /> : <VaRoutes />;
}

function OwnerRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/sessions" replace />} />
      <Route path="/sessions" element={<SessionsPage />} />
      <Route path="/approvals" element={<ApprovalsPage />} />
      <Route path="/session/new" element={<NewSession />} />
      <Route path="/session/:id/debug" element={<DebugView />} />
      <Route path="/session/:id" element={<SessionWorkspace />}>
        <Route index element={<Navigate to="table" replace />} />
        <Route path="table" element={<TableView />} />
        <Route path="cluster" element={<ClusterView />} />
        <Route path="architecture" element={<ArchitectureView />} />
        <Route path="split" element={<SplitView />} />
        <Route path="schedule" element={<ScheduleView />} />
        <Route path="articles" element={<ArticlesView />} />
        <Route path="exports" element={<ExportsView />} />
      </Route>
      <Route path="*" element={<Navigate to="/sessions" replace />} />
    </Routes>
  );
}

// VA routes (PRD §10.3): the wizard plus the restricted results surface
// (Table + Cluster + read-only Architecture). No split view, no project
// browser; any other path lands back on the wizard.
function VaRoutes() {
  return (
    <Routes>
      <Route path="/wizard" element={<Wizard />} />
      <Route path="/session/:id" element={<SessionWorkspace />}>
        <Route index element={<Navigate to="table" replace />} />
        <Route path="table" element={<TableView />} />
        <Route path="cluster" element={<ClusterView />} />
        <Route path="architecture" element={<ArchitectureView />} />
        <Route path="schedule" element={<ScheduleView />} />
        <Route path="exports" element={<ExportsView />} />
        <Route path="split" element={<Navigate to="../table" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/wizard" replace />} />
    </Routes>
  );
}
