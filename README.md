# English 7–10 Assessment Coverage Tracker

A static site for tracking which **Victorian Curriculum F–10 Version 2.0 English (Levels 7–10)** content descriptions have been assessed, by which assessment task, when, and for which class.

96 content descriptions: 24 per level (9 Language, 6 Literature, 9 Literacy).

**This is a record, not a checklist.** The site deliberately shows no completion percentage and no progress bars — full curriculum coverage isn't the goal. The summary counts what's been assessed, how many tasks it took, how much of it carries evidence notes, and what's been revisited more than once, so depth of assessment is what's visible.

## Where it lives

Repo `NMO-SOC/assessment-tracker`, published by GitHub Pages from `main` / root:

**https://nmo-soc.github.io/assessment-tracker/**

Sync worker: `https://silent-star-96b1.nicholas-morlin.workers.dev/` (Cloudflare, source in `worker/worker.js`).

## How the data works

`data/coverage.json` in this repo is the single source of truth. Every device that opens the site reads it, so they all show the same records. Saving commits straight back to that file.

A browser has no authority to write to a repo, so something has to hold the GitHub credential. It lives in a small Cloudflare worker (`worker/worker.js`) rather than in any browser — the site just calls the worker, and the worker commits. On the device you only ever type a passphrase.

| Layer | Where | Role |
|---|---|---|
| Source of truth | `data/coverage.json` | Read by every visitor. Full commit history of every change. |
| Credential | Cloudflare worker secret | Never in a browser, never in this repo. |
| Local cache | browser `localStorage` | Written instantly so nothing is lost offline; reconciled on the next sync. |

### One-time worker setup

1. Sign in at [dash.cloudflare.com](https://dash.cloudflare.com) (free plan, no card) → **Workers & Pages** → **Create** → **Create Worker**. Name it `assessment-sync`, deploy the placeholder.
2. **Edit code** → delete what's there → paste all of `worker/worker.js` → **Deploy**.
3. **Settings → Variables and Secrets** → add:

   | Name | Type | Value |
   |---|---|---|
   | `GITHUB_TOKEN` | Secret | a fine-grained PAT (see below) |
   | `PASSPHRASE` | Secret | any phrase you'll remember |
   | `REPO_OWNER` | Text | `NMO-SOC` |
   | `REPO_NAME` | Text | `assessment-tracker` |
   | `FILE_PATH` | Text | `data/coverage.json` |
   | `BRANCH` | Text | `main` |
   | `ALLOWED_ORIGIN` | Text | `https://nmo-soc.github.io` |

   The token: [GitHub → fine-grained tokens → generate new](https://github.com/settings/personal-access-tokens/new) **while signed in as NMO-SOC**, *Only select repositories* → `assessment-tracker`, *Repository permissions* → **Contents: Read and write**. Nothing else. This is the only place it's ever pasted.
4. Copy the worker URL and set `SYNC_URL` at the top of the script block in `index.html` to it. Commit and push.

Then on each device: **Data → Enable saving on this device**, type the passphrase once. That's all — no tokens, no expiry to chase.

`ALLOWED_ORIGIN` means only the published site can call the worker, and `PASSPHRASE` means only you can write. Leave `PASSPHRASE` unset and anyone who discovers the worker URL could edit the records — set it.

### The sync chip

Top right of the header, click it to sync on demand:

| Chip | Meaning |
|---|---|
| Read-only | No passphrase on this device. You see the shared records but can't save. |
| Synced *n*m ago | Everything is saved and shared. |
| Saving… | Push in flight (batched ~2s after your last edit). |
| Local only | You've made changes this device can't share yet. |
| Not saved | The push failed — records are safe locally. Check the passphrase, then Sync now. |
| This browser only | `SYNC_URL` is still empty; the worker isn't set up. |

Every record carries an id, and both ends merge on those ids: if another device saved while you were editing, its records are kept rather than overwritten, and records you deleted stay deleted. Commits retry on conflict.

### Export / import

Still under the **Data** menu — `coverage.json` for a manual backup, and CSV for reporting. Import replaces the working set and pushes it, so treat it as a restore.

To preview locally: `python3 -m http.server 8000` then open `http://localhost:8000`. Double-clicking `index.html` won't work — reading `data/coverage.json` needs http.

## Layout

The Curriculum view mirrors the VCAA document: one section per strand (Language, Literature, Literacy), sub-strand bands within it, and four columns — Level 7, 8, 9, 10 — so the same content description reads across the levels. Filtering to a single level collapses it to one column. Below 900px wide it stacks into a single column with level labels.

## Recording an assessment

Click any content description to open the side panel, then enter:

- **Assessment name** (required) — e.g. "Persuasive essay — Unit 2"
- **Date**
- **Class / cohort** — e.g. "9C". Autocompletes from classes you've already used.
- **Notes / evidence**

The same content description can carry multiple records (different classes, different tasks). Filter by class to see coverage for one group only.

Typing an assessment name that already exists fills in that task's date and class automatically, so records for one task stay consistent. Anything you type over by hand is left alone.

**Data → Tidy assessment names and dates** repairs records that already disagree: for each assessment task, whichever name and date most of its records use becomes the value for all of them. Ties go to the earliest date, or the longer spelling. It shows exactly what it will change and does nothing unless you confirm.

Each record has **Edit** and **Remove**. Editing opens the same fields in place and keeps the record's id, so an edit updates that record everywhere rather than creating a second one. Cancel discards the change.

## Dark mode

The moon/sun button in the header toggles it, and the choice is remembered per browser. With no choice made it follows your operating system's setting. It's a display preference only — stored separately from your records, never synced.

## Views and filters

- **Curriculum** view — the four-level grid. Assessed descriptions carry a tick, the assessment names, and a page icon where evidence notes exist. Ones with no records stay quiet rather than being flagged as gaps.
- **By assessment** view — every assessment you've recorded and the content descriptions it covered. Useful for checking an assessment task's spread.
- Filters: level, strand, with / without records, class, and free-text search (searches descriptions, codes, assessment names, and notes).
- **Report** view — a printable document, one page per year level per semester: tasks in date order, dates, classes, and the content descriptions each assessed with your criterion names and the full curriculum wording. Header carries the school name (the `SCHOOL` constant in `index.html`), footer carries the generation date. Print or save as PDF from the button; browser chrome, filters and the summary strip are excluded from print. Honours the level and class filters; ignores search and record filters so a page is never partial. Semester comes from the `S1_` / `S2_` prefix in the task name, falling back to the month of the date.
- **Export CSV** produces one row per content description per record — for reporting or importing into a spreadsheet.

## Files

Inside `assessment-tracker/` in the homepage repo:

```
index.html            the whole app (no build step, no dependencies)
data/curriculum.js    curriculum data loaded by the page
data/curriculum.json  same data as plain JSON, for other tools
data/coverage.json    the shared assessment records — source of truth
worker/worker.js      the Cloudflare sync worker (not served; deployed separately)
```

`SYNC_URL` at the top of the script block in `index.html` points at the worker. The repo, branch and file path are set as worker variables, not in the page.

Curriculum content descriptions are from the VCAA Victorian Curriculum F–10 Version 2.0, English Levels 7–10 (13 December 2023). To change the curriculum data, edit `data/curriculum.json` and regenerate `data/curriculum.js` as `window.CURRICULUM = <that json>;`.
