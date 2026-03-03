// Drive Scanner Test Dashboard — Cloudflare Worker
// Routes:
//   GET  /              → Dashboard HTML
//   POST /webhook       → Receive scanner payload → store in KV
//   GET  /api/payloads  → List stored payloads (JSON)
//   GET  /api/payloads/:id → Single payload by ID
//   DELETE /api/payloads → Clear all stored payloads
//   POST /api/trigger   → Trigger GitHub Actions workflow_dispatch

const GITHUB_REPO = "BoraIlkinonu/Chatbot-KB-Maintenance-Mechanism";
const WORKFLOW_FILE = "drive-scan-webhook.yml";
const WORKFLOW_REF = "drive-scan-webhook";
const KV_PREFIX = "payload:";
const TTL_SECONDS = 30 * 24 * 60 * 60; // 30 days

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // CORS headers for API routes
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    };

    if (method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    try {
      // --- Dashboard ---
      if (method === "GET" && path === "/") {
        return new Response(dashboardHTML(), {
          headers: { "Content-Type": "text/html; charset=utf-8" },
        });
      }

      // --- Receive webhook payload ---
      if (method === "POST" && path === "/webhook") {
        const payload = await request.json();
        const ts = new Date().toISOString();
        const key = KV_PREFIX + ts;
        await env.SCAN_PAYLOADS.put(key, JSON.stringify(payload), {
          expirationTtl: TTL_SECONDS,
        });
        console.log(`Stored payload: ${key}`);
        return new Response(JSON.stringify({ status: "stored", key: ts }), {
          status: 200,
          headers: { "Content-Type": "application/json", ...corsHeaders },
        });
      }

      // --- List payloads ---
      if (method === "GET" && path === "/api/payloads") {
        const list = await env.SCAN_PAYLOADS.list({ prefix: KV_PREFIX });
        const payloads = [];
        for (const key of list.keys) {
          const raw = await env.SCAN_PAYLOADS.get(key.name);
          if (raw) {
            const data = JSON.parse(raw);
            payloads.push({
              id: key.name.replace(KV_PREFIX, ""),
              timestamp: key.name.replace(KV_PREFIX, ""),
              summary: buildSummary(data),
            });
          }
        }
        // Sort newest first
        payloads.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
        return new Response(JSON.stringify(payloads), {
          headers: { "Content-Type": "application/json", ...corsHeaders },
        });
      }

      // --- Get single payload ---
      if (method === "GET" && path.startsWith("/api/payloads/")) {
        const id = decodeURIComponent(path.replace("/api/payloads/", ""));
        const raw = await env.SCAN_PAYLOADS.get(KV_PREFIX + id);
        if (!raw) {
          return new Response(JSON.stringify({ error: "Not found" }), {
            status: 404,
            headers: { "Content-Type": "application/json", ...corsHeaders },
          });
        }
        return new Response(raw, {
          headers: { "Content-Type": "application/json", ...corsHeaders },
        });
      }

      // --- Clear all payloads ---
      if (method === "DELETE" && path === "/api/payloads") {
        const list = await env.SCAN_PAYLOADS.list({ prefix: KV_PREFIX });
        for (const key of list.keys) {
          await env.SCAN_PAYLOADS.delete(key.name);
        }
        return new Response(
          JSON.stringify({ status: "cleared", count: list.keys.length }),
          {
            headers: { "Content-Type": "application/json", ...corsHeaders },
          }
        );
      }

      // --- Trigger GitHub Actions ---
      if (method === "POST" && path === "/api/trigger") {
        const { mode } = await request.json();
        const pat = env.GITHUB_PAT;
        if (!pat) {
          return new Response(
            JSON.stringify({ error: "GITHUB_PAT secret not configured on worker" }),
            {
              status: 500,
              headers: { "Content-Type": "application/json", ...corsHeaders },
            }
          );
        }

        const inputs = buildWorkflowInputs(mode);
        const ghUrl = `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

        const ghRes = await fetch(ghUrl, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${pat}`,
            Accept: "application/vnd.github+json",
            "User-Agent": "drive-scanner-dashboard",
            "X-GitHub-Api-Version": "2022-11-28",
          },
          body: JSON.stringify({ ref: WORKFLOW_REF, inputs }),
        });

        if (ghRes.status === 204) {
          return new Response(
            JSON.stringify({ status: "triggered", mode, inputs }),
            {
              headers: { "Content-Type": "application/json", ...corsHeaders },
            }
          );
        }
        const errBody = await ghRes.text();
        return new Response(
          JSON.stringify({
            error: "GitHub API error",
            status: ghRes.status,
            body: errBody,
          }),
          {
            status: 502,
            headers: { "Content-Type": "application/json", ...corsHeaders },
          }
        );
      }

      // --- List recent workflow runs with artifacts ---
      if (method === "GET" && path === "/api/runs") {
        const pat = env.GITHUB_PAT;
        if (!pat) {
          return new Response(
            JSON.stringify({ error: "GITHUB_PAT not configured" }),
            { status: 500, headers: { "Content-Type": "application/json", ...corsHeaders } }
          );
        }
        // Get recent runs for our workflow
        const runsRes = await fetch(
          `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=10`,
          {
            headers: {
              Authorization: `Bearer ${pat}`,
              Accept: "application/vnd.github+json",
              "User-Agent": "drive-scanner-dashboard",
              "X-GitHub-Api-Version": "2022-11-28",
            },
          }
        );
        const runsData = await runsRes.json();
        const runs = (runsData.workflow_runs || []).map((r) => ({
          id: r.id,
          status: r.status,
          conclusion: r.conclusion,
          created_at: r.created_at,
          updated_at: r.updated_at,
          html_url: r.html_url,
        }));

        const ghHeaders = {
          Authorization: `Bearer ${pat}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "drive-scanner-dashboard",
          "X-GitHub-Api-Version": "2022-11-28",
        };

        const results = [];
        for (const run of runs) {
          // Fetch jobs/steps for in-progress runs
          if (run.status !== "completed") {
            const jobsRes = await fetch(
              `https://api.github.com/repos/${GITHUB_REPO}/actions/runs/${run.id}/jobs`,
              { headers: ghHeaders }
            );
            const jobsData = await jobsRes.json();
            run.steps = [];
            for (const job of jobsData.jobs || []) {
              for (const step of job.steps || []) {
                run.steps.push({
                  name: step.name,
                  status: step.status,
                  conclusion: step.conclusion,
                  started_at: step.started_at,
                  completed_at: step.completed_at,
                });
              }
            }
            run.artifacts = [];
          } else {
            // Fetch artifacts for completed runs
            const artRes = await fetch(
              `https://api.github.com/repos/${GITHUB_REPO}/actions/runs/${run.id}/artifacts`,
              { headers: ghHeaders }
            );
            const artData = await artRes.json();
            run.artifacts = (artData.artifacts || []).map((a) => ({
              id: a.id,
              name: a.name,
              size_in_bytes: a.size_in_bytes,
              expired: a.expired,
              created_at: a.created_at,
            }));
            run.steps = [];
          }
          results.push(run);
        }
        return new Response(JSON.stringify(results), {
          headers: { "Content-Type": "application/json", ...corsHeaders },
        });
      }

      // --- Download artifact zip (proxy through worker) ---
      if (method === "GET" && path.startsWith("/api/artifacts/")) {
        const artifactId = path.replace("/api/artifacts/", "");
        const pat = env.GITHUB_PAT;
        if (!pat) {
          return new Response(
            JSON.stringify({ error: "GITHUB_PAT not configured" }),
            { status: 500, headers: { "Content-Type": "application/json", ...corsHeaders } }
          );
        }
        // GitHub returns a 302 redirect to the actual zip
        const ghRes = await fetch(
          `https://api.github.com/repos/${GITHUB_REPO}/actions/artifacts/${artifactId}/zip`,
          {
            headers: {
              Authorization: `Bearer ${pat}`,
              Accept: "application/vnd.github+json",
              "User-Agent": "drive-scanner-dashboard",
              "X-GitHub-Api-Version": "2022-11-28",
            },
            redirect: "follow",
          }
        );
        if (!ghRes.ok) {
          return new Response(
            JSON.stringify({ error: "Artifact download failed", status: ghRes.status }),
            { status: 502, headers: { "Content-Type": "application/json", ...corsHeaders } }
          );
        }
        return new Response(ghRes.body, {
          headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": `attachment; filename="artifact-${artifactId}.zip"`,
            ...corsHeaders,
          },
        });
      }

      return new Response("Not found", { status: 404 });
    } catch (err) {
      console.error(err);
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { "Content-Type": "application/json", ...corsHeaders },
      });
    }
  },
};

function buildWorkflowInputs(mode) {
  switch (mode) {
    case "scan":
      return { dry_run: "false", download: "false", full_sync: "false" };
    case "download":
      return { dry_run: "false", download: "true", full_sync: "false" };
    case "full_sync":
      return { dry_run: "false", download: "true", full_sync: "true" };
    case "dry_run":
      return { dry_run: "true", download: "false", full_sync: "false" };
    default:
      return { dry_run: "false", download: "true", full_sync: "false" };
  }
}

function buildSummary(data) {
  const changes = data.changes || {};
  const counts = {
    new: 0,
    modified: 0,
    deleted: 0,
    renamed: 0,
  };
  for (const term of Object.values(changes)) {
    if (Array.isArray(term)) {
      for (const ch of term) {
        const t = (ch.change_type || "").toLowerCase();
        if (t in counts) counts[t]++;
      }
    }
  }
  return {
    has_changes: data.has_changes || false,
    scan_time: data.scan_time || data.timestamp || null,
    ...counts,
    total: counts.new + counts.modified + counts.deleted + counts.renamed,
  };
}

// ---------------------------------------------------------------------------
// Dashboard HTML
// ---------------------------------------------------------------------------
function dashboardHTML() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Drive Scanner Dashboard</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242836;
    --border: #2e3345;
    --text: #e2e4ea;
    --text2: #8b8fa3;
    --accent: #6c8cff;
    --accent2: #4a6adf;
    --green: #3dd68c;
    --red: #f0544c;
    --orange: #ffa94d;
    --yellow: #ffd43b;
    --radius: 8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.5; padding: 24px; max-width: 1200px; margin: 0 auto;
  }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  h2 { font-size: 1.1rem; color: var(--text2); margin-bottom: 16px; }
  h3 { font-size: 1rem; margin-bottom: 8px; }

  .header { margin-bottom: 24px; display: flex; align-items: center; gap: 12px; }
  .header .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--green); }
  .header .dot.offline { background: var(--red); }
  .subtitle { color: var(--text2); font-size: 0.85rem; }

  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px; margin-bottom: 16px;
  }
  .card-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 12px;
  }

  /* Trigger Panel */
  .trigger-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  button {
    padding: 8px 16px; border: none; border-radius: var(--radius);
    font-size: 0.85rem; font-weight: 500; cursor: pointer;
    transition: opacity 0.15s;
  }
  button:hover { opacity: 0.85; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-scan { background: var(--accent); color: #fff; }
  .btn-download { background: var(--green); color: #111; }
  .btn-full { background: var(--orange); color: #111; }
  .btn-dry { background: var(--surface2); color: var(--text); border: 1px solid var(--border); }
  .btn-danger { background: var(--red); color: #fff; }
  .btn-sm { padding: 4px 10px; font-size: 0.78rem; }

  /* Active/inactive button states during a run */
  .btn-active {
    background: var(--green) !important; color: #111 !important;
    border-color: var(--green) !important;
    box-shadow: 0 0 12px rgba(61,214,140,0.3);
  }
  .btn-inactive {
    background: var(--surface2) !important; color: var(--text2) !important;
    border-color: var(--border) !important; opacity: 0.45;
  }

  /* Run card separators */
  .run-card {
    padding: 14px 0; border-bottom: 2px solid var(--border);
    margin-bottom: 2px;
  }
  .run-card:last-of-type { border-bottom: none; margin-bottom: 0; }

  /* Status message */
  .status-msg {
    margin-top: 8px; font-size: 0.82rem; color: var(--text2);
    min-height: 1.3em;
  }
  .status-msg.ok { color: var(--green); }
  .status-msg.err { color: var(--red); }

  /* Badge */
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600;
  }
  .badge-green { background: rgba(61,214,140,0.15); color: var(--green); }
  .badge-red { background: rgba(240,84,76,0.15); color: var(--red); }
  .badge-yellow { background: rgba(255,212,59,0.15); color: var(--yellow); }
  .badge-blue { background: rgba(108,140,255,0.15); color: var(--accent); }

  /* Summary bar */
  .summary-bar { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
  .summary-item {
    display: flex; align-items: center; gap: 6px;
    font-size: 0.85rem;
  }
  .summary-num { font-weight: 700; font-size: 1.2rem; }

  /* Table */
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th {
    text-align: left; padding: 8px 10px; color: var(--text2);
    border-bottom: 1px solid var(--border); font-weight: 500; font-size: 0.78rem;
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); }
  tr:hover td { background: var(--surface2); }
  .term-header td {
    font-weight: 700; padding: 12px 10px 6px;
    border-bottom: 2px solid var(--accent); background: transparent !important;
  }

  /* Change type badges */
  .ct-new { color: var(--green); }
  .ct-modified { color: var(--orange); }
  .ct-deleted { color: var(--red); }
  .ct-renamed { color: var(--accent); }

  /* Activity feed */
  .activity-item {
    padding: 8px 0; border-bottom: 1px solid var(--border);
    font-size: 0.85rem; display: flex; gap: 12px;
  }
  .activity-item:last-child { border-bottom: none; }
  .activity-time { color: var(--text2); white-space: nowrap; font-size: 0.8rem; }

  /* Accordion */
  details { margin-bottom: 4px; }
  summary {
    cursor: pointer; padding: 8px 0; font-size: 0.85rem;
    color: var(--accent); list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  summary::before { content: "\\25B6  "; font-size: 0.7rem; }
  details[open] > summary::before { content: "\\25BC  "; }
  .rev-list { padding-left: 16px; margin-top: 4px; }
  .rev-item {
    font-size: 0.82rem; padding: 4px 0;
    border-bottom: 1px solid var(--border);
  }
  .rev-item:last-child { border-bottom: none; }

  /* Payload history list */
  .history-item {
    padding: 10px 12px; border-bottom: 1px solid var(--border);
    cursor: pointer; display: flex; justify-content: space-between;
    align-items: center; font-size: 0.85rem; transition: background 0.1s;
  }
  .history-item:hover { background: var(--surface2); }
  .history-item.active { background: var(--surface2); border-left: 3px solid var(--accent); }

  /* Raw JSON */
  .raw-json {
    background: var(--surface2); padding: 12px; border-radius: var(--radius);
    font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.78rem;
    max-height: 500px; overflow: auto; white-space: pre-wrap; word-break: break-all;
  }

  /* Download info */
  .dl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.85rem; }
  .dl-label { color: var(--text2); }

  /* Runs table */
  .run-status { font-weight: 600; }
  .run-success { color: var(--green); }
  .run-failure { color: var(--red); }
  .run-pending { color: var(--yellow); }
  .btn-dl {
    background: var(--accent); color: #fff; padding: 4px 10px;
    border-radius: var(--radius); font-size: 0.78rem; text-decoration: none;
    border: none; cursor: pointer; display: inline-block;
  }
  .btn-dl:hover { opacity: 0.85; }

  /* Tooltip */
  .btn-wrap { position: relative; display: inline-block; }
  .tooltip {
    display: none; position: absolute; left: 50%; top: calc(100% + 10px);
    transform: translateX(-50%); z-index: 100;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px 18px;
    width: 300px; box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    font-size: 0.82rem; line-height: 1.6; color: var(--text);
  }
  .tooltip::before {
    content: ''; position: absolute; top: -6px; left: 50%;
    transform: translateX(-50%) rotate(45deg);
    width: 10px; height: 10px;
    background: var(--surface); border-left: 1px solid var(--border);
    border-top: 1px solid var(--border);
  }
  .btn-wrap:hover .tooltip { display: block; }
  /* Step progress */
  .steps { display: flex; gap: 2px; flex-wrap: wrap; margin-top: 6px; }
  .step {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 0.72rem; padding: 2px 8px; border-radius: 4px;
    background: var(--surface2); color: var(--text2);
    white-space: nowrap;
  }
  .step-done { background: rgba(61,214,140,0.12); color: var(--green); }
  .step-running { background: rgba(255,212,59,0.15); color: var(--yellow); }
  .step-fail { background: rgba(240,84,76,0.12); color: var(--red); }
  .step-skip { opacity: 0.4; }
  .step-icon { font-size: 0.68rem; }

  .tooltip h4 { font-size: 0.88rem; margin-bottom: 6px; color: var(--text); }
  .tooltip p { margin: 0 0 8px; color: var(--text2); }
  .tooltip p:last-child { margin-bottom: 0; }
  .tooltip .tip-label { color: var(--accent); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
  .tooltip .tip-what { color: var(--text); }
  .tooltip .tip-when { color: var(--text2); font-style: italic; }

  /* Layout */
  .two-col { display: grid; grid-template-columns: 280px 1fr; gap: 16px; }
  @media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }

  /* Empty state */
  .empty { color: var(--text2); text-align: center; padding: 40px 0; }

  /* Spinner */
  .spinner {
    display: inline-block; width: 14px; height: 14px;
    border: 2px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Auto-refresh toggle */
  .auto-refresh { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; }
  .toggle {
    position: relative; width: 36px; height: 20px; cursor: pointer;
  }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle .slider {
    position: absolute; inset: 0; background: var(--surface2);
    border-radius: 10px; transition: 0.2s; border: 1px solid var(--border);
  }
  .toggle .slider::before {
    content: ''; position: absolute; width: 14px; height: 14px;
    border-radius: 50%; background: var(--text2); left: 2px; top: 2px;
    transition: 0.2s;
  }
  .toggle input:checked + .slider { background: var(--accent); border-color: var(--accent); }
  .toggle input:checked + .slider::before { transform: translateX(16px); background: #fff; }
</style>
</head>
<body>

<div class="header">
  <div class="dot" id="statusDot"></div>
  <div>
    <h1>Drive Scanner Test Dashboard</h1>
    <div class="subtitle">Webhook receiver &amp; workflow trigger</div>
  </div>
  <div style="margin-left: auto;">
    <div class="auto-refresh">
      <label class="toggle">
        <input type="checkbox" id="autoRefresh" checked>
        <span class="slider"></span>
      </label>
      <span>Auto-refresh (30s)</span>
    </div>
  </div>
</div>

<!-- Trigger Panel -->
<div class="card">
  <h3>Trigger Workflow</h3>
  <div style="display: flex; gap: 12px; flex-wrap: wrap; margin-top: 10px;">
    <div class="btn-wrap">
      <button class="btn-dry trigger-btn" data-mode="dry_run" onclick="triggerWorkflow('dry_run')">Dry Run</button>
      <div class="tooltip">
        <h4>Dry Run</h4>
        <div class="tip-label">What it does</div>
        <p class="tip-what">Looks at Google Drive and compares with the last known state. Shows you what files changed, were added, or deleted.</p>
        <p class="tip-what">Nothing is saved. The "last known state" stays the same. Results still appear on this dashboard.</p>
        <div class="tip-label" style="margin-top:8px">When to use</div>
        <p class="tip-when">You just want to peek at what changed without affecting anything.</p>
      </div>
    </div>
    <div class="btn-wrap">
      <button class="btn-scan trigger-btn" data-mode="scan" onclick="triggerWorkflow('scan')">Scan</button>
      <div class="tooltip">
        <h4>Scan</h4>
        <div class="tip-label">What it does</div>
        <p class="tip-what">Same as Dry Run, but also <strong>saves the new snapshot</strong>. Next time you scan, it will compare against this scan's result.</p>
        <p class="tip-what">No files are downloaded. Only the change report is saved.</p>
        <div class="tip-label" style="margin-top:8px">When to use</div>
        <p class="tip-when">You want to check what changed and record it, but don't need the actual files.</p>
      </div>
    </div>
    <div class="btn-wrap">
      <button class="btn-download trigger-btn" data-mode="download" onclick="triggerWorkflow('download')">Scan + Download</button>
      <div class="tooltip">
        <h4>Scan + Download</h4>
        <div class="tip-label">What it does</div>
        <p class="tip-what">Scans, saves the snapshot, <strong>and downloads the actual changed files</strong> (PPTX, DOCX, etc). Files appear in the "Recent Runs" section below as a downloadable zip.</p>
        <div class="tip-label" style="margin-top:8px">When to use</div>
        <p class="tip-when">A teacher updated a file and you need the new version. Click the download link in "Recent Runs" once the scan finishes.</p>
      </div>
    </div>
    <div class="btn-wrap">
      <button class="btn-full trigger-btn" data-mode="full_sync" onclick="triggerWorkflow('full_sync')">Full Sync</button>
      <div class="tooltip">
        <h4>Full Sync</h4>
        <div class="tip-label">What it does</div>
        <p class="tip-what">Forgets everything. Treats every file in Drive as brand new. <strong>Downloads ALL files</strong> from all 3 term folders, not just changed ones.</p>
        <div class="tip-label" style="margin-top:8px">When to use</div>
        <p class="tip-when">First-time setup, or something got out of sync and you want a clean slate.</p>
      </div>
    </div>
  </div>
  <div class="status-msg" id="triggerStatus"></div>
</div>

<!-- Recent Runs & Downloads -->
<div class="card">
  <div class="card-header">
    <h3>Recent Runs &amp; Downloads</h3>
    <button class="btn-sm btn-scan" onclick="loadRuns()">Refresh</button>
  </div>
  <div id="runsPanel"><div class="empty">Click Refresh to load recent workflow runs</div></div>
</div>

<!-- Main content -->
<div class="two-col">

  <!-- Left: History -->
  <div>
    <div class="card" style="position: sticky; top: 24px;">
      <div class="card-header">
        <h3>Payload History</h3>
        <button class="btn-danger btn-sm" onclick="clearAll()">Clear All</button>
      </div>
      <div id="historyList"><div class="empty">Loading...</div></div>
    </div>
  </div>

  <!-- Right: Payload Detail -->
  <div id="detailPanel">
    <div class="card"><div class="empty">Select a payload or wait for new webhook data</div></div>
  </div>

</div>

<script>
const BASE = '';
let payloads = [];
let selectedId = null;
let refreshTimer = null;

// --- Init ---
loadPayloads();
startAutoRefresh();

document.getElementById('autoRefresh').addEventListener('change', (e) => {
  if (e.target.checked) startAutoRefresh(); else stopAutoRefresh();
});

function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = setInterval(loadPayloads, 30000);
}
function stopAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
}

// --- API calls ---
async function loadPayloads() {
  try {
    const res = await fetch(BASE + '/api/payloads');
    payloads = await res.json();
    renderHistory();
    document.getElementById('statusDot').classList.remove('offline');
    // Auto-select newest if none selected
    if (!selectedId && payloads.length > 0) {
      selectPayload(payloads[0].id);
    }
  } catch (e) {
    document.getElementById('statusDot').classList.add('offline');
  }
}

async function selectPayload(id) {
  selectedId = id;
  renderHistory();
  const res = await fetch(BASE + '/api/payloads/' + encodeURIComponent(id));
  const data = await res.json();
  renderDetail(data, id);
}

async function clearAll() {
  if (!confirm('Delete all stored payloads?')) return;
  await fetch(BASE + '/api/payloads', { method: 'DELETE' });
  payloads = [];
  selectedId = null;
  renderHistory();
  document.getElementById('detailPanel').innerHTML =
    '<div class="card"><div class="empty">All payloads cleared</div></div>';
}

let runsPollingTimer = null;
let activeMode = null;
let lastRunsJson = '';

function setButtonsRunning(mode) {
  activeMode = mode;
  document.querySelectorAll('.trigger-btn').forEach(btn => {
    if (btn.dataset.mode === mode) {
      btn.classList.add('btn-active');
      btn.disabled = false;
    } else {
      btn.classList.add('btn-inactive');
      btn.disabled = true;
    }
  });
}
function resetButtons() {
  activeMode = null;
  document.querySelectorAll('.trigger-btn').forEach(btn => {
    btn.classList.remove('btn-active', 'btn-inactive');
    btn.disabled = false;
  });
}

async function triggerWorkflow(mode) {
  setButtonsRunning(mode);
  try {
    const res = await fetch(BASE + '/api/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    const data = await res.json();
    if (data.error) {
      resetButtons();
      setTriggerStatus('Error: ' + data.error + (data.body ? ' — ' + data.body : ''), 'err');
    } else {
      setTriggerStatus('', '');
      setTimeout(loadRuns, 5000);
      startRunsPolling();
    }
  } catch (e) {
    resetButtons();
    setTriggerStatus('Network error: ' + e.message, 'err');
  }
}

function startRunsPolling() {
  stopRunsPolling();
  runsPollingTimer = setInterval(loadRuns, 10000);
}
function stopRunsPolling() {
  if (runsPollingTimer) clearInterval(runsPollingTimer);
  runsPollingTimer = null;
}

function buildRunsHTML(runs) {
  let html = '';
  for (let i = 0; i < runs.length; i++) {
    const run = runs[i];
    const isRunning = run.status !== 'completed';
    const isFailed = run.conclusion === 'failure';
    const cls = run.conclusion === 'success' ? 'run-success' : isFailed ? 'run-failure' : 'run-pending';
    const statusText = isRunning ? run.status : run.conclusion;

    html += '<div class="run-card">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center">';
    html += '<div>';
    html += '<span class="run-status ' + cls + '">';
    if (isRunning) html += '<span class="spinner" style="margin-right:6px"></span>';
    html += esc(statusText) + '</span>';
    html += ' <span style="color:var(--text2);font-size:0.82rem">' + esc(formatTime(run.created_at)) + '</span>';
    html += '</div>';
    html += '<div style="display:flex;gap:8px;align-items:center">';
    if (run.artifacts && run.artifacts.length > 0) {
      for (const a of run.artifacts) {
        if (!a.expired) {
          html += '<a class="btn-dl" href="' + BASE + '/api/artifacts/' + a.id + '" title="' + esc(a.name) + ' (' + esc(formatSize(a.size_in_bytes)) + ')">' + esc(a.name) + '</a>';
        } else {
          html += '<span style="color:var(--text2);font-size:0.78rem">' + esc(a.name) + ' (expired)</span>';
        }
      }
    }
    if (!isFailed) {
      html += '<a href="' + esc(run.html_url) + '" target="_blank" style="color:var(--accent);font-size:0.78rem">View on GitHub</a>';
    }
    html += '</div></div>';

    if (run.steps && run.steps.length > 0) {
      html += '<div class="steps">';
      for (const step of run.steps) {
        let sCls = '';
        let icon = '';
        if (step.status === 'completed' && step.conclusion === 'success') { sCls = 'step-done'; icon = '\\u2713'; }
        else if (step.status === 'completed' && step.conclusion === 'failure') { sCls = 'step-fail'; icon = '\\u2717'; }
        else if (step.status === 'completed' && step.conclusion === 'skipped') { sCls = 'step-skip'; icon = '\\u2014'; }
        else if (step.status === 'in_progress') { sCls = 'step-running'; icon = '\\u25B6'; }
        else { sCls = ''; icon = '\\u25CB'; }
        html += '<span class="step ' + sCls + '"><span class="step-icon">' + icon + '</span>' + esc(step.name) + '</span>';
      }
      html += '</div>';
    }
    html += '</div>';
  }
  return html;
}

async function loadRuns() {
  const panel = document.getElementById('runsPanel');
  // Show spinner only on very first load
  if (!panel.dataset.loaded) {
    panel.innerHTML = '<div class="empty"><span class="spinner"></span> Loading runs...</div>';
  }
  try {
    const res = await fetch(BASE + '/api/runs');
    const runs = await res.json();
    if (runs.error) { panel.innerHTML = '<div class="empty">' + esc(runs.error) + '</div>'; stopRunsPolling(); return; }
    if (runs.length === 0) { panel.innerHTML = '<div class="empty">No runs yet</div>'; panel.dataset.loaded = '1'; stopRunsPolling(); return; }

    const hasInProgress = runs.some(r => r.status !== 'completed');

    // Only update DOM if data actually changed (prevents flicker)
    const newJson = JSON.stringify(runs);
    if (newJson !== lastRunsJson) {
      lastRunsJson = newJson;
      let html = buildRunsHTML(runs);
      if (hasInProgress) {
        html += '<div style="font-size:0.78rem;color:var(--text2);margin-top:12px;padding-top:8px"><span class="spinner" style="margin-right:4px"></span>Updating every 10s...</div>';
      }
      panel.innerHTML = html;
      panel.dataset.loaded = '1';
    }

    if (!hasInProgress && runsPollingTimer) {
      stopRunsPolling();
      resetButtons();
      setTriggerStatus('', '');
      loadPayloads();
    }
  } catch (e) {
    // Don't overwrite on transient network errors during polling
    if (!panel.dataset.loaded) {
      panel.innerHTML = '<div class="empty" style="color:var(--red)">Failed to load runs: ' + esc(e.message) + '</div>';
    }
  }
}

function setTriggerStatus(msg, cls) {
  const el = document.getElementById('triggerStatus');
  el.innerHTML = msg;
  el.className = 'status-msg' + (cls ? ' ' + cls : '');
}

// --- Rendering ---
function renderHistory() {
  const el = document.getElementById('historyList');
  if (payloads.length === 0) {
    el.innerHTML = '<div class="empty">No payloads received yet</div>';
    return;
  }
  el.innerHTML = payloads.map(p => {
    const s = p.summary;
    const active = p.id === selectedId ? ' active' : '';
    const badge = s.has_changes
      ? '<span class="badge badge-yellow">' + s.total + ' changes</span>'
      : '<span class="badge badge-green">No changes</span>';
    const time = formatTime(p.timestamp);
    return '<div class="history-item' + active + '" onclick="selectPayload(\\''+esc(p.id)+'\\')"><div>' + time + '</div>' + badge + '</div>';
  }).join('');
}

function renderDetail(data, id) {
  const panel = document.getElementById('detailPanel');
  let html = '';

  // --- Overview ---
  html += '<div class="card">';
  html += '<div class="card-header"><h3>Scan Overview</h3>';
  html += '<span class="badge ' + (data.has_changes ? 'badge-yellow' : 'badge-green') + '">'
    + (data.has_changes ? 'Changes Detected' : 'No Changes') + '</span>';
  html += '</div>';

  const scanTime = data.scan_time || data.timestamp || id;
  html += '<div style="font-size:0.85rem; color:var(--text2); margin-bottom: 12px;">Received: ' + formatTime(id) + ' &middot; Scan: ' + formatTime(scanTime) + '</div>';

  // Summary bar
  const changes = data.changes || {};
  const counts = { new: 0, modified: 0, deleted: 0, renamed: 0 };
  const allChanges = [];
  for (const [term, items] of Object.entries(changes)) {
    if (Array.isArray(items)) {
      for (const ch of items) {
        const t = (ch.change_type || '').toLowerCase();
        if (t in counts) counts[t]++;
        allChanges.push({ ...ch, _term: term });
      }
    }
  }
  html += '<div class="summary-bar">';
  html += summaryItem(counts.new, 'New', 'ct-new');
  html += summaryItem(counts.modified, 'Modified', 'ct-modified');
  html += summaryItem(counts.deleted, 'Deleted', 'ct-deleted');
  html += summaryItem(counts.renamed, 'Renamed', 'ct-renamed');
  html += '</div>';
  html += '</div>';

  // --- Changes Table ---
  if (allChanges.length > 0) {
    html += '<div class="card"><h3>Changes by Term</h3>';
    html += '<table><thead><tr><th>File</th><th>Type</th><th>Lessons</th><th>Size</th><th>Modified By</th></tr></thead><tbody>';

    // Group by term
    const byTerm = {};
    for (const ch of allChanges) {
      const t = ch._term;
      if (!byTerm[t]) byTerm[t] = [];
      byTerm[t].push(ch);
    }
    for (const [term, items] of Object.entries(byTerm)) {
      html += '<tr class="term-header"><td colspan="5">' + esc(term) + '</td></tr>';
      for (const ch of items) {
        const ct = (ch.change_type || '').toLowerCase();
        html += '<tr>';
        html += '<td>' + esc(ch.file_name || ch.name || '—') + '</td>';
        html += '<td><span class="ct-' + ct + '">' + esc(ch.change_type || '—') + '</span></td>';
        html += '<td>' + esc(formatLessons(ch.lessons)) + '</td>';
        html += '<td>' + esc(formatSize(ch.size)) + '</td>';
        html += '<td>' + esc(ch.last_modified_by || ch.modifier || '—') + '</td>';
        html += '</tr>';
      }
    }
    html += '</tbody></table></div>';
  }

  // --- Activity Feed ---
  const activity = data.activity || data.recent_activity || [];
  if (activity.length > 0) {
    html += '<div class="card"><h3>Activity Feed</h3>';
    for (const a of activity) {
      html += '<div class="activity-item">';
      html += '<span class="activity-time">' + esc(formatTime(a.time || a.timestamp || '')) + '</span>';
      html += '<span>' + esc(a.user || a.actor || '') + ' ' + esc(a.action || a.description || '') + '</span>';
      html += '</div>';
    }
    html += '</div>';
  }

  // --- Revisions ---
  const revisions = data.revisions || data.revision_details || {};
  const revEntries = Object.entries(revisions);
  if (revEntries.length > 0) {
    html += '<div class="card"><h3>Revisions</h3>';
    for (const [fileName, revs] of revEntries) {
      html += '<details><summary>' + esc(fileName) + ' (' + (Array.isArray(revs) ? revs.length : 0) + ' revisions)</summary>';
      html += '<div class="rev-list">';
      if (Array.isArray(revs)) {
        for (const r of revs) {
          html += '<div class="rev-item">';
          html += '<strong>' + esc(formatTime(r.modifiedTime || r.time || '')) + '</strong> — ';
          html += esc(r.lastModifyingUser || r.user || 'Unknown');
          if (r.size) html += ' &middot; ' + esc(formatSize(r.size));
          html += '</div>';
        }
      }
      html += '</div></details>';
    }
    html += '</div>';
  }

  // --- Download Info ---
  const dl = data.downloads || data.download_info;
  if (dl) {
    html += '<div class="card"><h3>Download Info</h3><div class="dl-grid">';
    if (dl.total_files != null) {
      html += '<span class="dl-label">Files downloaded</span><span>' + dl.total_files + '</span>';
    }
    if (dl.total_size != null) {
      html += '<span class="dl-label">Total size</span><span>' + esc(formatSize(dl.total_size)) + '</span>';
    }
    if (dl.path) {
      html += '<span class="dl-label">Path</span><span>' + esc(dl.path) + '</span>';
    }
    if (dl.errors && dl.errors.length > 0) {
      html += '<span class="dl-label">Errors</span><span class="ct-deleted">' + dl.errors.length + ' errors</span>';
    }
    html += '</div></div>';
  }

  // --- Raw JSON ---
  html += '<div class="card">';
  html += '<details><summary style="color:var(--text2)">Raw JSON Payload</summary>';
  html += '<div class="raw-json">' + esc(JSON.stringify(data, null, 2)) + '</div>';
  html += '</details></div>';

  panel.innerHTML = html;
}

function summaryItem(count, label, cls) {
  return '<div class="summary-item"><span class="summary-num ' + cls + '">' + count + '</span><span>' + label + '</span></div>';
}

// --- Helpers ---
function esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatTime(t) {
  if (!t) return '—';
  try {
    const d = new Date(t);
    if (isNaN(d.getTime())) return String(t);
    return d.toLocaleString();
  } catch { return String(t); }
}

function formatSize(bytes) {
  if (bytes == null) return '—';
  const n = Number(bytes);
  if (isNaN(n)) return String(bytes);
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatLessons(lessons) {
  if (!lessons) return '—';
  if (Array.isArray(lessons)) return lessons.join(', ');
  return String(lessons);
}
</script>
</body>
</html>`;
}
