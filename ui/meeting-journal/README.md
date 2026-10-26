# Planner meeting journal

Production integration of the previously selected LFP journal-editor design.
The Python capability-protected server owns all reads and writes through Planner;
React state is only an unsaved draft. Visual editing and Markdown share one value.

Install/build: `npm ci`, `npm run build`. The resulting JS/CSS and third-party notices
are checked in under `src/okama_planner/_journal_assets` and included in wheel/sdist.
Node and npm are not needed to run the installed Python application. Dependencies
live outside the Python runtime; `node_modules` must never enter Git/distributions.

Browser regression: `node scripts/check-orca.mjs OWNED_PAGE OUTPUT_JSON` on a
synthetic task-owned local database. Never run this mutating probe against a real
client database. See `docs/design-qa-meeting-journal.md` for capture/validation.
