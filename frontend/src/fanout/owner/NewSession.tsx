import { useNavigate, useSearchParams } from "react-router-dom";
import { SiloDiscovery } from "./SiloDiscovery";

// The session-creation + pipeline flow (M2–M6) lives in SiloDiscovery. M7 wraps
// it as a route; exiting returns to the session browser, where the finished
// session can be reopened in the three views. A `?type=` param (set by the
// content-type cards on the sessions page) preselects the output and skips the
// chooser.
export function NewSession() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const type = params.get("type");
  const initialContentType =
    type === "blog_post" || type === "local_seo_page" ? type : undefined;
  return (
    <SiloDiscovery
      onExit={() => navigate("/fanout/sessions")}
      initialContentType={initialContentType}
    />
  );
}
