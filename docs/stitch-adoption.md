# Stitch UI adoption

Implemented 18 October 2026. The user selected both light and dark variants,
with a persistent theme switcher, from the **YouTube Metadata Harvester** project
(`projects/10367671453701923805`, updated `2026-10-18T19:10:33.745860Z`).
Stitch was read only; no remote designs were changed.

## Sources and route mapping

All screen names below are under `projects/10367671453701923805/screens/`.

| Journey | Route / implementation | Light screen | Dark screen |
| --- | --- | --- | --- |
| Configure extraction | `/`, `templates/index.html` | `3f1afc834e134da9a8df27c31c0c689c` | `720705588c674d7cb88dba937e2f8038` |
| Live progress | `/monitor`, `templates/runs.html`, `run-status.html` | `e69682599e504c3396119f4925f1b055` | `5392b08905a54fb983dea181f85ecdbe` |
| History / artifacts | `/runs`, `templates/runs.html`, `run-status.html` | `1d58e9d22d7b49a2bbba824189465809` | `6e744c0c2d4b4f3e9ed62bac49a9c563` |
| Credentials / quota | `/api-key`, `templates/api-key.html` | `b44f72f692de4a6ea7126421e329dcf0` | `91cb833e205b48b39eda93490ec7a206` |

Screenshots and inspected HTML are kept locally in the ignored
`docs/stitch-references/` directory. Full-size PNGs are 2560 pixels wide;
Stitch canvas instances establish a 1280 CSS-pixel desktop layout. Initial
512-pixel thumbnails were replaced with full-size downloads. Screen-specific
HTML and screenshots establish the source: project theme metadata alone does not.
The uploaded `index.html` is baseline context, not an adopted alternate.
No separate design-system asset was treated as authoritative over these screens.

## Adoption and preservation

- Adopted the dark top navigation, compact source selector, grouped form panels,
  configuration/summary split, red extraction action, pale lavender light surfaces,
  charcoal dark surfaces, and Geist / JetBrains Mono type roles.
- Adapted desktop compositions to stacked phone layouts. The shared CSS defines
  both themes; preference persists locally and otherwise follows the OS setting.
- Kept FastAPI, Jinja, filesystem checkpoints, extraction services and POST/download
  contracts. Replaced external Tailwind/Alpine/HTMX delivery with local CSS and JS;
  existing fragment endpoints still drive four-second progress refresh.
- Preserved search / playlist / channel modes, batch inputs, every search filter,
  page bounds and early stopping, output selection, all progress counters and
  timestamps, error messages, downloads, resume, key validation / primary / delete,
  recent daily operation history and quota caveats. Enabled the already-supported
  Markdown output in the form. Invalid submissions restore submitted values safely.
- History cards retain all existing metrics rather than squeezing them into the
  source's table. The live monitor uses real checkpoint cards and filters by the
  selected run ID; it does not invent a terminal log stream or throughput.
- Totals explicitly cover the most recent 50 runs. Dedupe remains per-run.

## Unsupported mockup features

Pause/stop, folder opening, ZIP bundles, Parquet, raw terminal streams, record
thumbnails, disk/memory telemetry, presets and API balances are not supported by
the existing UI service contracts and were not added as decorative controls.
No sample metrics, credentials, version numbers or health claims became app data.
Quota usage remains an estimate from successful calls; keys from one Cloud
project still share its quota. No upstream balance or percentage is fabricated.

## Verification

- Baseline: existing suite passed, 36 tests. Captured the old templates against
  isolated fixture data; the old CDN-dependent appearance cannot be guaranteed
  when external resources are unavailable.
- Final suite: `.venv/bin/python -m pytest -q` — 38 passed, including added route
  coverage for history/monitor recovery and artifacts, plus safely restored form
  values containing script delimiters.
- `node --check static/app.js` and `git diff --check` passed.
- Headless Chrome: console, history, monitor and keys in both themes at 1280×960
  and 390×844, 16 screenshots. Checked mode visibility, source counting, CLI flags,
  saved theme after reload, filtering through live refresh, clearing no-match
  state and artifact download. No JavaScript errors or horizontal overflow.
- Browser fixtures used dummy credentials and disposable runs under
  `/tmp/stitch-youtube/preview-runs`; no real extraction or API validation ran.
- Local screenshots and fixture/browser scripts are under `/tmp/stitch-youtube/`;
  migrated screenshots are also copied to `docs/stitch-references/preview/`.
- Impeccable context/detector engine unavailable in the sandbox; source inspection
  and independent review supplement browser and repository checks.

## Delivery slices

Completed: shared shell/tokens/themes; extraction console; history/live checkpoint
views; credential/usage settings; functional and responsive checks. The redesign
supersedes the old appearance guidance in architecture decision 2 while keeping
its service-first, stateless and capability-preservation requirements.

Independent finish review accepted the source adoption and capability-preserving
adaptations. Its sole material finding was the dark-theme page-limit text contrast;
that now uses the readable red text token, confirmed in desktop/phone recaptures
and cleared by the reviewer's verdict pass. Design tokens are recorded in
`DESIGN.md` and `.impeccable/design.json`.
