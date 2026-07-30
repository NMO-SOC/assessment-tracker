# English 7–10 Assessment Coverage Tracker

A static site for tracking which **Victorian Curriculum F–10 Version 2.0 English (Levels 7–10)** content descriptions have been assessed, by which assessment task, when, and for which class.

96 content descriptions: 24 per level (9 Language, 6 Literature, 9 Literacy).

## Publishing to GitHub Pages

1. Create a new repository on GitHub (e.g. `english-assessment-coverage`).
2. Upload the contents of this folder (`index.html`, `data/`, `.nojekyll`, `README.md`) to the repo root.
3. Repo **Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main`, Folder = `/ (root)`. Save.
4. The site appears at `https://<username>.github.io/<repo>/` within a minute or two.

Via command line:

```bash
cd "Assessment Marker"
git init && git add . && git commit -m "English 7-10 assessment coverage tracker"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

## How the data works

Two layers:

| Layer | File | Role |
|---|---|---|
| Working copy | browser `localStorage` | Every tick you make is saved instantly to the browser you're using. |
| Source of truth | `data/coverage.json` | Committed to the repo. Loaded on first visit in a fresh browser, and shared across devices. |

Workflow to sync across devices:

1. Tick things off in the site.
2. Click **Export coverage.json** — it downloads.
3. Replace `data/coverage.json` in the repo with the downloaded file and commit.
4. On another device, open the site and click **Reload from repo file**.

`Reload from repo file` and the automatic first-load only work over http(s) — i.e. on GitHub Pages or a local server, not by double-clicking `index.html`. Everything else works offline.

To preview locally: `python3 -m http.server 8000` then open `http://localhost:8000`.

## Recording an assessment

Click any content description to expand it, then enter:

- **Assessment name** (required) — e.g. "Persuasive essay — Unit 2"
- **Date**
- **Class / cohort** — e.g. "9C". Autocompletes from classes you've already used.
- **Notes / evidence**

The same content description can carry multiple records (different classes, different tasks). Filter by class to see coverage for one group only.

## Views and filters

- **Curriculum** view — grouped by strand and sub-strand, with per-level and per-strand progress bars.
- **By assessment** view — every assessment you've recorded and the content descriptions it covered. Useful for checking an assessment task's spread.
- Filters: level, strand, assessed / not yet assessed, class, and free-text search (searches descriptions, codes, assessment names, and notes).
- **Export CSV** produces one row per content description per record — for reporting or importing into a spreadsheet.

## Files

```
index.html            the whole app (no build step, no dependencies)
data/curriculum.js    curriculum data loaded by the page
data/curriculum.json  same data as plain JSON, for other tools
data/coverage.json    committed coverage records
.nojekyll             stops GitHub Pages running Jekyll over the files
```

Curriculum content descriptions are from the VCAA Victorian Curriculum F–10 Version 2.0, English Levels 7–10 (13 December 2023). To change the curriculum data, edit `data/curriculum.json` and regenerate `data/curriculum.js` as `window.CURRICULUM = <that json>;`.
