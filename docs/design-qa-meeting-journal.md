# Meeting journal validation

Reference: the owner's previously selected LFP journal-editor prototype and
`docs/design/meeting-journal/04-interactive-visual.png` in the LFP repository.
Implementation reuses its React/Tiptap composition and Phosphor icons, replacing
only demo state with capability-protected Planner API persistence.

Browser interaction checks use an owned synthetic Orca tab. They verify Markdown
round trip and visual formatting, unsaved navigation protection, save/reload,
invalid dates retaining the draft, server-assigned IDs, save-from-dialog without
duplicates, absence of external resources and an empty browser console.
The repeatable script is `ui/meeting-journal/scripts/check-orca.mjs`.

Orca's emulated screenshots repeated/cropped the page; these are rejected as visual
evidence. Final desktop/mobile captures use an isolated headless Chrome profile,
not the user's browser profile. Captures and combined reference/implementation
comparison are stored in the task's ignored `tmp/` (synthetic records only).

The production UI deliberately links to the real client card/plans instead of
inactive prototype tabs, labels itself as a local database, and reports real saved
state. Fallback system fonts are used offline instead of requesting Google Fonts.
These are intentional functional/content changes; typography differences are P3.

Final comparison and mobile dimensions are recorded after capture. No real client
input is used in screenshots or browser test fixtures.

Final visual evidence: `tmp/journal-comparison.png` places the 1487×1058 reference
beside the 1487×1058 implementation with the same synthetic first meeting/content.
`tmp/journal-verified-mobile.png` is 390×844, device scale 1. Desktop grid, sidebar,
list/editor divider, metadata, toolbar and note hierarchy match the selected target.
Mobile stacks the list and editor, keeps all metadata accessible and fixes save/cancel
to the bottom without horizontal overflow. The real saved status intentionally differs
from the source's unsaved demonstration state. No actionable P0/P1/P2 difference remains;
P3: fallback font metrics and linked production navigation labels.

final result: passed
