import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  generateArchitecture,
  getArchitecture,
  getSummary,
  type ArchitectureJson,
} from "../../shared/api";
import { useSession } from "../SessionWorkspace";

// Architecture View (PRD §9.3): two-panel site map. Left = pillars → supporting
// articles; right = the selected node's editorial fields + internal linking
// matrix. Regenerate re-runs §7.11. "Send to Brief Generator" is disabled —
// content-platform-api doesn't exist yet (§16.2).
export function ArchitectureView() {
  const { sessionId, role } = useSession();
  const isVA = role === "va";
  const qc = useQueryClient();
  const arch = useQuery({ queryKey: ["architecture", sessionId], queryFn: () => getArchitecture(sessionId), retry: false });
  const summary = useQuery({ queryKey: ["summary", sessionId], queryFn: () => getSummary(sessionId) });

  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const regen = useMutation({
    mutationFn: () => generateArchitecture(sessionId),
    onSuccess: () => {
      setBusy(true);
      qc.invalidateQueries({ queryKey: ["summary", sessionId] });
    },
  });

  // While regenerating, the session goes status=running and the workspace polls
  // /summary. When it lands, pull the fresh architecture.
  const status = summary.data?.status;
  useEffect(() => {
    if (busy && status && status !== "running") {
      qc.invalidateQueries({ queryKey: ["architecture", sessionId] });
      setBusy(false);
    }
  }, [busy, status, qc, sessionId]);

  if (arch.isLoading) return <p className="muted">Loading architecture…</p>;

  if (arch.isError || !arch.data) {
    return (
      <div className="card">
        <p style={{ margin: 0, fontWeight: 600 }}>No architecture generated yet.</p>
        {isVA ? (
          <p className="muted">Your workspace owner generates the pillar / supporting-article site map for this session.</p>
        ) : (
          <>
            <p className="muted">Generate the pillar / supporting-article site map and its internal links.</p>
            <button className="btn btn-primary" style={{ width: "auto" }} disabled={busy || regen.isPending} onClick={() => regen.mutate()}>
              {busy || regen.isPending ? <><span className="spinner-sm" />Generating…</> : "Generate architecture"}
            </button>
          </>
        )}
      </div>
    );
  }

  const a = arch.data.architecture_json;
  return (
    <div>
      <div className="arch-toolbar">
        <span className="muted">
          Generated {new Date(arch.data.generated_at).toLocaleString()}
          {arch.data.is_user_edited && " · edited"}
        </span>
        {a.link_health && (() => {
          const lh = a.link_health;
          const ok = lh.orphan_articles === 0 && lh.orphan_pillars === 0 && lh.dangling_links === 0;
          return (
            <span
              className="muted"
              style={{ color: ok ? "inherit" : "#c0392b" }}
              title="No-orphan / no-dangling audit (§15.2 #3). Each page links to ≤5 others; every article has ≥1 inbound link."
            >
              {ok
                ? "· ✓ no orphans, no dangling links"
                : `· ⚠ ${lh.orphan_articles} orphan articles, ${lh.dangling_links} dangling links`}
            </span>
          );
        })()}
        {!isVA && (
          <button className="btn btn-ghost" style={{ width: "auto" }} disabled={busy || regen.isPending} onClick={() => regen.mutate()}>
            {busy || regen.isPending ? <><span className="spinner-sm" />Regenerating…</> : "Regenerate architecture"}
          </button>
        )}
      </div>
      <ArchPanels arch={a} selected={selected} onSelect={setSelected} />
    </div>
  );
}

type NodeSel = string; // "pillar:<topic_id>" | "article:<article_id>"

function ArchPanels({
  arch,
  selected,
  onSelect,
}: {
  arch: ArchitectureJson;
  selected: NodeSel | null;
  onSelect: (s: NodeSel) => void;
}) {
  const pillarByTopic = useMemo(() => new Map(arch.pillars.map((p) => [p.topic_id, p])), [arch.pillars]);
  const articleById = useMemo(() => new Map(arch.supporting_articles.map((x) => [x.article_id, x])), [arch.supporting_articles]);
  const articlesForPillar = (topicId: string) =>
    arch.supporting_articles.filter((x) => x.parent_pillar_topic_id === topicId);

  const sel = selected ?? (arch.pillars[0] ? `pillar:${arch.pillars[0].topic_id}` : null);

  return (
    <div className="arch-layout">
      <aside className="arch-tree">
        {arch.pillars.map((p) => {
          const kids = articlesForPillar(p.topic_id);
          return (
            <div key={p.topic_id} className="arch-pillar">
              <button
                className={"arch-node arch-node-pillar" + (sel === `pillar:${p.topic_id}` ? " arch-node-active" : "")}
                onClick={() => onSelect(`pillar:${p.topic_id}`)}
              >
                {p.title}
                {p.degraded && <span className="badge badge-warn" style={{ marginLeft: 6 }}>stub</span>}
                <span className="topic-group-count">{kids.length}</span>
              </button>
              {kids.map((x) => (
                <button
                  key={x.article_id}
                  className={"arch-node arch-node-article" + (sel === `article:${x.article_id}` ? " arch-node-active" : "")}
                  onClick={() => onSelect(`article:${x.article_id}`)}
                >
                  {x.name}
                </button>
              ))}
            </div>
          );
        })}
        {arch.skipped_silos.length > 0 && (
          <p className="muted" style={{ padding: "8px 12px" }}>Skipped (no articles): {arch.skipped_silos.join(", ")}</p>
        )}
      </aside>

      <section className="arch-detail">
        {sel?.startsWith("pillar:") && (() => {
          const p = pillarByTopic.get(sel.slice("pillar:".length));
          if (!p) return null;
          return (
            <div>
              <h2 className="arch-detail-title">{p.title}</h2>
              <DetailLine label="Type">Pillar · {p.silo_name}</DetailLine>
              <DetailLine label="Target keyword">{p.target_keyword}</DetailLine>
              {p.summary
                ? <DetailLine label="Summary">{p.summary}</DetailLine>
                : <DetailLine label="Title & summary"><span className="muted">written by the writer module</span></DetailLine>}
              {p.h2_outline.length > 0 && <DetailLine label="H2 outline">{p.h2_outline.join(" · ")}</DetailLine>}
              <DetailLine label={`Links down to (${p.supporting_article_ids.length})`}>
                {p.supporting_article_ids.map((id) => articleById.get(id)?.name ?? id).join(", ") || "—"}
              </DetailLine>
              <DetailLine label="Lateral pillar links">
                {p.lateral_pillar_links.map((tid) => pillarByTopic.get(tid)?.title ?? tid).join(", ") || "—"}
              </DetailLine>
              <BriefButton />
            </div>
          );
        })()}

        {sel?.startsWith("article:") && (() => {
          const x = articleById.get(sel.slice("article:".length));
          if (!x) return null;
          const parent = pillarByTopic.get(x.parent_pillar_topic_id);
          return (
            <div>
              <h2 className="arch-detail-title">{x.name}</h2>
              <DetailLine label="Type">Supporting article · {x.intent}</DetailLine>
              <DetailLine label="Links up to">{parent?.title ?? "—"}</DetailLine>
              <DetailLine label="Lateral article links">
                {x.lateral_article_links.map((id) => articleById.get(id)?.name ?? id).join(", ") || "—"}
              </DetailLine>
              <BriefButton />
            </div>
          );
        })()}
      </section>
    </div>
  );
}

function BriefButton() {
  return (
    <button className="btn btn-ghost" style={{ width: "auto", marginTop: 16 }} disabled title="Brief Generator is unavailable in this environment">
      Send to Brief Generator
    </button>
  );
}

function DetailLine({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="detail-line">
      <span className="detail-label">{label}</span>
      <span className="detail-value">{children}</span>
    </div>
  );
}
