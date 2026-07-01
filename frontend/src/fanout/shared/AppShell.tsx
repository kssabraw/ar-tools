import { type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getMe, listApprovals } from "./api";
import { useAuth } from "./auth";
import { CLIENT_SCOPE } from "./clientScope";

// Shared app frame for every Owner/VA view. Mirrors the AR Tools suite chrome:
// a dark slate left sidebar (indigo brand mark + "AR Tools" wordmark, a quick-nav
// block back into the suite, the module's icon nav, and sign-out at the foot)
// with page content in the main column. The "Topic Fanout" module label sits
// under the wordmark so it's clear which tool this is.

// Lucide-style inline icons. The suite uses lucide-react; we inline the few
// glyphs we need rather than add the dependency to the vendored app.
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}
const HomeIcon = () => (
  <Icon>
    <path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    <polyline points="9 22 9 12 15 12 15 22" />
  </Icon>
);
const DashboardIcon = () => (
  <Icon>
    <rect width="7" height="9" x="3" y="3" rx="1" />
    <rect width="7" height="5" x="14" y="3" rx="1" />
    <rect width="7" height="9" x="14" y="12" rx="1" />
    <rect width="7" height="5" x="3" y="16" rx="1" />
  </Icon>
);
const FolderIcon = () => (
  <Icon>
    <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
  </Icon>
);
const PlusIcon = () => (
  <Icon>
    <path d="M5 12h14" />
    <path d="M12 5v14" />
  </Icon>
);
const CheckIcon = () => (
  <Icon>
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
    <path d="m9 11 3 3L22 4" />
  </Icon>
);
const SparkIcon = () => (
  <Icon>
    <path d="M9.94 15.5A2 2 0 0 0 8.5 14.06l-6.14-1.58a.5.5 0 0 1 0-.96L8.5 9.94A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0L14.06 8.5A2 2 0 0 0 15.5 9.94l6.14 1.58a.5.5 0 0 1 0 .96L15.5 14.06a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0Z" />
  </Icon>
);
const LogOutIcon = () => (
  <Icon>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <polyline points="16 17 21 12 16 7" />
    <line x1="21" x2="9" y1="12" y2="12" />
  </Icon>
);

interface NavItem {
  label: string;
  to: string;
  icon: ReactNode;
  badge?: number;
}

function navActive(pathname: string, to: string): boolean {
  if (to === "/fanout/sessions") {
    // Sessions is "home" for owners; stay lit while browsing or inside a
    // session workspace, but not on the New-session form.
    return (
      pathname === "/fanout" ||
      pathname === "/fanout/" ||
      pathname.startsWith("/fanout/sessions") ||
      (pathname.startsWith("/fanout/session/") && !pathname.startsWith("/fanout/session/new"))
    );
  }
  return pathname === to || pathname.startsWith(to + "/");
}

export function AppShell({ children }: { children: ReactNode }) {
  const { signOut } = useAuth();
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });
  const isOwner = me.data?.role === "owner";
  const { pathname } = useLocation();
  // Cross-app shortcuts back into the AR Tools suite (a separate app at the site
  // root, so these are plain full-page links, not router navigation). Dashboard
  // only appears when Fanout was opened scoped to a client — its id is the suite
  // client id passed in via the Content Scheduler card.
  const suiteClientId = CLIENT_SCOPE.clientId;
  // VAs have no session browser; their home is the wizard (PRD §10.3).
  const home = isOwner ? "/fanout/sessions" : "/fanout/wizard";

  // Pending-approval badge (PRD §11.3 step 3), owner-only, 30s polling.
  const approvals = useQuery({
    queryKey: ["approvals"],
    queryFn: listApprovals,
    enabled: isOwner,
    refetchInterval: 30000,
  });
  const pendingCount = approvals.data?.length ?? 0;

  const nav: NavItem[] = isOwner
    ? [
        { label: "Sessions", to: "/fanout/sessions", icon: <FolderIcon /> },
        { label: "New session", to: "/fanout/session/new", icon: <PlusIcon /> },
        { label: "Approvals", to: "/fanout/approvals", icon: <CheckIcon />, badge: pendingCount },
      ]
    : [{ label: "New keyword map", to: "/fanout/wizard", icon: <SparkIcon /> }];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link to={home} className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="sidebar-brand-text">
            <span className="brand-name">AR Tools</span>
            <span className="sidebar-module">Topic Fanout</span>
          </span>
        </Link>

        <nav className="sidebar-nav">
          {/* Quick-nav back into the suite (full-page links to the root app). */}
          <div className="sidebar-group">
            <a href="/" className="sidebar-link">
              <HomeIcon />
              <span>Home</span>
            </a>
            {suiteClientId && (
              <a href={`/clients/${suiteClientId}`} className="sidebar-link">
                <DashboardIcon />
                <span>Dashboard</span>
              </a>
            )}
          </div>

          {/* Topic Fanout module nav (in-app router links). */}
          {nav.map((item) => {
            const active = navActive(pathname, item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`sidebar-link${active ? " active" : ""}`}
              >
                {item.icon}
                <span>{item.label}</span>
                {item.badge ? <span className="nav-badge">{item.badge}</span> : null}
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-foot">
          {me.data && (
            <div className="sidebar-user">
              <span className="sidebar-email">{me.data.email}</span>
              <span className="role-badge">{me.data.role}</span>
            </div>
          )}
          <button className="sidebar-signout" onClick={() => signOut()}>
            <LogOutIcon />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      <main className="app-main">{children}</main>
    </div>
  );
}
