import { useNavigate } from "react-router-dom";
import { SiloDiscovery } from "./SiloDiscovery";

// The session-creation + pipeline flow (M2–M6) lives in SiloDiscovery. M7 wraps
// it as a route; exiting returns to the project browser, where the finished
// session can be reopened in the three views.
export function NewSession() {
  const navigate = useNavigate();
  return <SiloDiscovery onExit={() => navigate("/projects")} />;
}
