import { type CSSProperties, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getMe, listApprovals } from "./api";

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
const FolderIcon = () => (
  <Icon>
    <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />
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
  const me = useQuery({ queryKey: ["me"], queryFn: getMe });
  const isOwner = me.data?.role === "owner";
  const { pathname } = useLocation();

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
        { label: "Approvals", to: "/fanout/approvals", icon: <CheckIcon />, badge: pendingCount },
      ]
    : [{ label: "New keyword map", to: "/fanout/wizard", icon: <SparkIcon /> }];

  // Merged into the suite (Option C): the suite Layout provides the app sidebar
  // (global nav, user, sign-out). Fan-out renders inside the suite's main column
  // and keeps only its own module sub-nav as a horizontal bar at the top — no
  // second sidebar.
  return (
    <div className="app-main">
      <div style={topBarStyle}>
        <nav style={navRowStyle}>
          {nav.map((item) => {
            const active = navActive(pathname, item.to);
            return (
              <Link key={item.to} to={item.to} style={navLinkStyle(active)}>
                {item.icon}
                <span>{item.label}</span>
                {item.badge ? <span style={navBadgeStyle}>{item.badge}</span> : null}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </div>
  );
}

const topBarStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 20,
  padding: "10px 24px",
  borderBottom: "1px solid var(--border)",
  background: "var(--surface)",
  position: "sticky",
  top: 0,
  zIndex: 5,
};
const navRowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 4 };
function navLinkStyle(active: boolean): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 12px",
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 600,
    textDecoration: "none",
    color: active ? "var(--accent)" : "var(--text-muted)",
    background: active ? "var(--accent-soft)" : "transparent",
  };
}
const navBadgeStyle: CSSProperties = {
  minWidth: 18,
  padding: "0 6px",
  borderRadius: 999,
  fontSize: 11,
  fontWeight: 700,
  background: "var(--accent)",
  color: "#fff",
  textAlign: "center",
  lineHeight: "18px",
};
