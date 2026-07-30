/*
  Assessment tracker sync worker
  ------------------------------
  Holds the GitHub credential server-side so no token ever sits in a browser.

  GET   /   -> { version, updated, coverage }        current records, read from the repo
  POST  /   -> { ok, coverage }                      merge + commit records to the repo

  Environment (Cloudflare dashboard -> Settings -> Variables):
    GITHUB_TOKEN    secret. Fine-grained PAT, Contents: read and write, this repo only.
    PASSPHRASE      secret, optional. If set, saving requires it. If unset, anyone who
                    knows this worker's URL can save. Set it.
    REPO_OWNER      plain text, e.g. NMO-SOC
    REPO_NAME       plain text, e.g. nmo-soc.github.io
    FILE_PATH       plain text, e.g. assessment-tracker/data/coverage.json
    BRANCH          plain text, e.g. main
    ALLOWED_ORIGIN  plain text, e.g. https://nmo-soc.github.io
*/

const JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"};

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "*";
    const cors = {
      "Access-Control-Allow-Origin": allowed === "*" ? "*" : allowed,
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
      "Vary": "Origin"
    };
    const reply = (status, body) =>
      new Response(JSON.stringify(body), {status, headers: {...JSON_HEADERS, ...cors}});

    if (request.method === "OPTIONS") return new Response(null, {status: 204, headers: cors});
    if (allowed !== "*" && origin && origin !== allowed) return reply(403, {error: "Origin not allowed"});

    const cfg = {
      owner: env.REPO_OWNER,
      repo: env.REPO_NAME,
      path: env.FILE_PATH,
      branch: env.BRANCH || "main"
    };
    if (!env.GITHUB_TOKEN || !cfg.owner || !cfg.repo || !cfg.path)
      return reply(500, {error: "Worker is missing GITHUB_TOKEN, REPO_OWNER, REPO_NAME or FILE_PATH"});

    try {
      if (request.method === "GET") {
        const {json} = await readFile(env, cfg);
        return reply(200, json);
      }

      if (request.method === "POST") {
        let body;
        try { body = await request.json(); }
        catch { return reply(400, {error: "Body must be JSON"}); }

        if (env.PASSPHRASE) {
          const given = String(body.passphrase || "");
          if (!timingSafeEqual(given, env.PASSPHRASE))
            return reply(401, {error: "Wrong passphrase"});
        }

        const local = sanitise(body.coverage);
        if (!local) return reply(400, {error: "coverage must be an object of arrays"});
        const seen = new Set(Array.isArray(body.seenIds) ? body.seenIds : []);

        for (let attempt = 0; attempt < 3; attempt++) {
          const {json, sha} = await readFile(env, cfg);
          const merged = mergeCoverage(json.coverage || {}, local, seen);
          const payload = JSON.stringify({version: 1, updated: new Date().toISOString(), coverage: merged}, null, 1) + "\n";
          const res = await gh(env, `https://api.github.com/repos/${cfg.owner}/${cfg.repo}/contents/${encodePath(cfg.path)}`, {
            method: "PUT",
            body: JSON.stringify({
              message: `Update assessment records (${Object.keys(merged).length} content descriptions)`,
              content: b64encode(payload),
              sha: sha || undefined,
              branch: cfg.branch
            })
          });
          if (res.ok) return reply(200, {ok: true, coverage: merged});
          if (res.status !== 409) {
            const detail = await res.text();
            return reply(502, {error: githubMessage(res.status), detail: detail.slice(0, 300)});
          }
          await new Promise(r => setTimeout(r, 250 * (attempt + 1)));
        }
        return reply(409, {error: "The repo file kept changing while saving. Try again."});
      }

      return reply(405, {error: "Use GET or POST"});
    } catch (err) {
      return reply(500, {error: String(err && err.message || err)});
    }
  }
};

/* ---------- GitHub ---------- */

function gh(env, url, init = {}) {
  return fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "assessment-tracker-worker",
      ...(init.body ? {"Content-Type": "application/json"} : {})
    }
  });
}

async function readFile(env, cfg) {
  const url = `https://api.github.com/repos/${cfg.owner}/${cfg.repo}/contents/${encodePath(cfg.path)}?ref=${encodeURIComponent(cfg.branch)}`;
  const res = await gh(env, url, {cf: {cacheTtl: 0}});
  if (res.status === 404) return {json: {version: 1, updated: null, coverage: {}}, sha: null};
  if (!res.ok) throw new Error(githubMessage(res.status));
  const file = await res.json();
  let json = {coverage: {}};
  try { json = JSON.parse(b64decode(file.content)); } catch { /* treat as empty */ }
  if (!json || typeof json !== "object") json = {coverage: {}};
  return {json, sha: file.sha};
}

function githubMessage(status) {
  if (status === 401) return "The worker's GitHub token was rejected. Regenerate it and update GITHUB_TOKEN.";
  if (status === 403) return "GitHub refused the write. The token needs Contents: read and write on this repo.";
  if (status === 404) return "The worker can't see that repo or file path.";
  return `GitHub returned ${status}.`;
}

const encodePath = p => p.split("/").map(encodeURIComponent).join("/");

/* ---------- merge ----------
   Records carry stable ids. Anything the client hasn't seen is kept (added on another
   device); anything it had seen but no longer holds was deleted deliberately.        */

function mergeCoverage(remote, local, seen) {
  const out = {};
  for (const [code, list] of Object.entries(local)) out[code] = list.slice();
  const localIds = new Set(Object.values(local).flat().map(r => r.id));
  for (const [code, list] of Object.entries(remote || {})) {
    for (const r of list || []) {
      if (!r || !r.id) continue;
      if (localIds.has(r.id)) continue;
      if (seen.has(r.id)) continue;
      (out[code] = out[code] || []).push(r);
    }
  }
  for (const code of Object.keys(out)) if (!out[code].length) delete out[code];
  return out;
}

/* ---------- validation ---------- */

const FIELDS = ["id", "assessment", "date", "cls", "notes"];

function sanitise(cov) {
  if (!cov || typeof cov !== "object" || Array.isArray(cov)) return null;
  const codes = Object.keys(cov);
  if (codes.length > 500) return null;
  const out = {};
  for (const code of codes) {
    if (!/^VC2E\d{1,2}(LA|LE|LY)\d{2}$/.test(code)) continue;
    const list = cov[code];
    if (!Array.isArray(list)) return null;
    const clean = [];
    for (const r of list.slice(0, 100)) {
      if (!r || typeof r !== "object" || !r.id) continue;
      const rec = {};
      for (const f of FIELDS) rec[f] = typeof r[f] === "string" ? r[f].slice(0, 2000) : "";
      if (!rec.assessment) continue;
      clean.push(rec);
    }
    if (clean.length) out[code] = clean;
  }
  return out;
}

function timingSafeEqual(a, b) {
  const ea = new TextEncoder().encode(a), eb = new TextEncoder().encode(b);
  if (ea.length !== eb.length) return false;
  let diff = 0;
  for (let i = 0; i < ea.length; i++) diff |= ea[i] ^ eb[i];
  return diff === 0;
}

/* ---------- base64 (unicode safe) ---------- */

function b64encode(str) {
  const bytes = new TextEncoder().encode(str);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}
function b64decode(b64) {
  const bin = atob(String(b64).replace(/\s/g, ""));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}
