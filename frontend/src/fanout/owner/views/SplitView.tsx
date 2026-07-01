import { TableView } from "./TableView";
import { ClusterView } from "./ClusterView";

// Split View (PRD §9): Table + Cluster side-by-side. Desktop only — on narrow
// screens the panes stack (see .split-layout in index.css). Both panes read the
// same shared query cache, so no extra fetches.
export function SplitView() {
  return (
    <div className="split-layout">
      <div className="split-pane">
        <h3 className="split-pane-title">Table</h3>
        <TableView />
      </div>
      <div className="split-pane">
        <h3 className="split-pane-title">Cluster</h3>
        <ClusterView />
      </div>
    </div>
  );
}
