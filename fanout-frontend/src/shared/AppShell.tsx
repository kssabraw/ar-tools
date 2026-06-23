import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getMe, listApprovals } from "./api";
import { useAuth } from "./auth";
import { CLIENT_SCOPE } from "./clientScope";

// Shared top bar + page frame for every Owner view. The brand links home; the
// right side shows the signed-in user and a sign-out control.
export function AppShell({ children }: { children: ReactNode }) {
  const { signOut } = useAuth();
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });
  const isOwner = me.data?.role === "owner";
  // Cross-app shortcuts back into the AR Tools suite (a separate app at the site
  // root, so these are plain full-page links, not router navigation). Dashboard
  // only appears when Fanout was opened scoped to a client — its id is the suite
  // client id passed in via the Content Scheduler card.
  const suiteClientId = CLIENT_SCOPE.clientId;
  // VAs have no project browser; their home is the wizard (PRD §10.3).
  const home = isOwner ? "/projects" : "/wizard";

  // Pending-approval badge (PRD §11.3 step 3), owner-only, 30s polling.
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: listApprovals,
    enabled: isOwner,
    refetchInterval: 30000,
  });
  const pendingCount = approvals.data?.length ?? 0;

  return (
    <>
      <header className="topbar">
        <Link to={home} className="brand" style={{ textDecoration: "none", color: "inherit" }}>
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Topic Fanout</span>
        </Link>
        <div className="topbar-user">
          <a href="/" className="topbar-link">
            Home
          </a>
          {suiteClientId && (
            <a href={`/clients/${suiteClientId}`} className="topbar-link">
              Dashboard
            </a>
          )}
          {isOwner && (
            <Link to="/approvals" className="topbar-link">
              Approvals
              {pendingCount > 0 && <span className="nav-badge">{pendingCount}</span>}
            </Link>
          )}
          {me.data && (
            <>
              <span>{me.data.email}</span>
              <span className="role-badge">{me.data.role}</span>
            </>
          )}
          <button className="btn btn-ghost" onClick={() => signOut()}>
            Sign out
          </button>
        </div>
      </header>
      {children}
    </>
  );
}
