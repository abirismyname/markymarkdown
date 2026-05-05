#!/usr/bin/env python3
"""
Seed PRDs and fleet-routing labels onto open MarkyMarkdown issues.

Why this exists
---------------
Each leaf-level open issue in this repo was imported as a one-line brainstorm
from `issues.md`. Before we can dispatch GitHub Copilot CLI's `/fleet` command
across them, every issue needs a consistent PRD body and routing labels so
each parallel agent gets a crisp, independently-shippable scope.

This script:
  1. Creates (or updates) the routing labels.
  2. For every open issue *except* the 13 umbrella/theme trackers, sets the
     issue body to a templated PRD and applies the right label set.

Usage
-----
    # Authenticate first with a token that can write Issues (repo scope).
    gh auth login

    # Dry-run (prints what would change, no API writes):
    python3 scripts/seed_fleet_prds.py --dry-run

    # Apply:
    python3 scripts/seed_fleet_prds.py

    # Re-apply even if the PRD marker is already present:
    python3 scripts/seed_fleet_prds.py --force

Idempotency
-----------
The rendered PRD body starts with an HTML marker comment
(`<!-- prd:v1 -->`). On re-runs we skip any issue whose body already
contains that marker, unless `--force` is passed. Labels are always
re-applied (gh treats this as a no-op if already set).

Excluded issues (umbrella / theme trackers, do NOT touch):
    #130, #127, #122, #116, #111, #107, #99, #94, #88, #83, #77, #71, #63
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

REPO = "abirismyname/markymarkdown"
PRD_MARKER = "<!-- prd:v1 -->"

EXCLUDED = {130, 127, 122, 116, 111, 107, 99, 94, 88, 83, 77, 71, 63}

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

LABELS: list[tuple[str, str, str]] = [
    # name, color (hex, no #), description
    ("fleet:ready",      "0E8A16", "Well-scoped; safe to dispatch via /fleet"),
    ("fleet:needs-spec", "FBCA04", "Needs more design before an agent can implement"),
    ("fleet:blocked",    "B60205", "Depends on another open issue"),
    ("size:S",           "C2E0C6", "Small: < 1 day, isolated change"),
    ("size:M",           "FEF2C0", "Medium: 1-3 days, multi-file"),
    ("size:L",           "F9D0C4", "Large: > 3 days or cross-cutting"),
    ("area:ui",          "1D76DB", "SwiftUI views / AppKit windows"),
    ("area:cli",         "5319E7", "Bundled markitdown CLI / Process invocation"),
    ("area:settings",    "0052CC", "AppSettingsStore / Preferences UI"),
    ("area:packaging",   "BFDADC", "DMG, extensions, distribution"),
    ("area:ai",          "D93F0B", "Apple Foundation Models / Vision / on-device ML"),
    ("wave:1",           "EDEDED", "Wave 1 — Joy & UX polish (low risk, isolated)"),
    ("wave:2",           "EDEDED", "Wave 2 — Settings & profiles foundation"),
    ("wave:3",           "EDEDED", "Wave 3 — Output destinations"),
    ("wave:4",           "EDEDED", "Wave 4 — System integration extensions"),
    ("wave:5",           "EDEDED", "Wave 5 — Conversion power-ups"),
    ("wave:6",           "EDEDED", "Wave 6 — Distribution, trust, AI (human review)"),
]

# ---------------------------------------------------------------------------
# Conventions block — appended verbatim to every PRD
# ---------------------------------------------------------------------------

CONVENTIONS = """\
## Repo conventions (must follow)

- Read [`AGENTS.md`](../blob/main/AGENTS.md) and [`CLAUDE.md`](../blob/main/CLAUDE.md) before starting.
- **Swift 6 strict concurrency** — all shared mutable state must be `@MainActor` or `Sendable`. No new sendability warnings.
- **Menu-bar only** — the app is `LSUIElement = true`. Do not call `NSApplication.shared.setActivationPolicy(.regular)` or add Dock presence.
- **Output naming rule** — write next to the input: `foo.pdf` → `foo.pdf.md`; on collision suffix ` (1)`, ` (2)`, …
- **UserDefaults keys** — only the four established keys are allowed:
  `settings.cliPath`, `settings.keepDataURIs`, `settings.colorScheme`, `com.markitdown.conversionCount`.
  Any new key must be declared in `Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift`.
- **Workflow** — branch `feat/…` or `fix/…`, never push to `main`, open a PR.
- **Validation** — `swift build --configuration release` and `swift test --verbose` must pass.
- **UX delight** — preserve `celebrationMessages`, `checkMilestone()`, `playfulErrorMessage(_:)`, and the menu-bar VoiceOver strings.
"""

# ---------------------------------------------------------------------------
# Per-issue PRD data
# ---------------------------------------------------------------------------
# Each entry is keyed by issue number. Fields:
#   goal         — one sentence, user-visible behavior
#   files        — list of repo-relative paths or path globs the work likely touches
#   accept       — 3-5 bullets, must include at least one swift test expectation
#   oos          — bullets describing scope to avoid
#   wave         — 1..6
#   area         — ui|cli|settings|packaging|ai
#   size         — S|M|L
#   fleet        — ready|needs-spec|blocked
#   blocked_by   — optional list of issue numbers this depends on

ISSUES: dict[int, dict] = {

    # ---------------- Wave 1 — Joy & UX polish ----------------
    100: dict(
        goal="First-launch onboarding tour that highlights the menu-bar icon, drag targets, Preferences, and the joy features.",
        files=[
            "Sources/MarkitdownUI/Controllers/StatusBarController.swift",
            "Sources/MarkitdownUI/Controllers/DropWindowController.swift",
            "Sources/MarkitdownUI/Views/ (new OnboardingView.swift)",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (add `settings.onboardingCompleted` after declaring it here)",
        ],
        accept=[
            "On first launch (no `settings.onboardingCompleted` flag), a 3–4 step tour appears centered on the screen.",
            "Tour can be dismissed at any step; dismissal sets the flag and never re-appears.",
            "A “Show onboarding again” button is available in Preferences.",
            "`swift test --verbose` passes; add a unit test that verifies the flag is honored.",
        ],
        oos=["Animated coach marks attached to system menu bar coordinates", "Multi-language onboarding copy (handled in #108)"],
        wave=1, area="ui", size="M", fleet="ready",
    ),
    101: dict(
        goal="Let users add or replace celebration messages and the emoji set used after a successful conversion.",
        files=[
            "Sources/MarkitdownUI/Views/DropZoneView.swift (the `celebrationMessages` array)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare new key)",
        ],
        accept=[
            "Preferences gains a “Celebrations” tab/section with an editable list of messages.",
            "User-provided messages are merged with built-in defaults; user can disable defaults.",
            "Selection on success uses the merged pool (still random).",
            "`swift test --verbose` passes; unit-test the merge/disable logic.",
        ],
        oos=["Per-format celebration overrides", "Cloud-synced custom packs"],
        wave=1, area="settings", size="S", fleet="ready",
    ),
    102: dict(
        goal="Optional sound effects on success/failure with a global mute toggle.",
        files=[
            "Sources/MarkitdownUI/ViewModels/ConversionManager.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.soundsEnabled`)",
            "Sources/MarkitdownUI/Resources/ (bundled .aiff files)",
        ],
        accept=[
            "Two short, royalty-free chimes ship in `Resources/` and are played via `NSSound` on success/failure.",
            "Sounds default to OFF; Preferences exposes the toggle.",
            "Honors system “Play user interface sound effects”.",
            "`swift test --verbose` passes; cover the enabled/disabled branches with a fake player.",
        ],
        oos=["Custom user-supplied sound files", "Per-event volume"],
        wave=1, area="settings", size="S", fleet="ready",
    ),
    103: dict(
        goal="Show a confetti / Vortex burst when the user hits a 10/50/100 conversion milestone.",
        files=[
            "Sources/MarkitdownUI/Views/DropZoneView.swift",
            "Sources/MarkitdownUI/ViewModels/ConversionManager.swift (existing `checkMilestone()`)",
            "Package.swift (already pins ConfettiSwiftUI 1.1.0 / Vortex 1.0.4 — reuse them)",
        ],
        accept=[
            "On milestone trigger, a confetti burst overlays the drop window for ~2s and is then removed.",
            "Honors the reduced-motion preference from #110 (no confetti when on).",
            "Does not block subsequent drops or interactions.",
            "`swift test --verbose` passes; add a test that `checkMilestone()` posts the expected notification.",
        ],
        oos=["Confetti for every successful conversion", "Per-milestone custom palettes"],
        wave=1, area="ui", size="S", fleet="ready",
    ),
    104: dict(
        goal="Extend the existing color-scheme setting with an accent-color picker that themes the drop window.",
        files=[
            "Sources/MarkitdownUI/Views/DropZoneView.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.accentColor`)",
        ],
        accept=[
            "Preferences exposes a color-well bound to a new accent setting.",
            "Drop-zone borders, progress, and success states use the chosen accent.",
            "`auto`, `light`, `dark` color-scheme behavior is unchanged.",
            "`swift test --verbose` passes; unit-test default fallback when value is missing.",
        ],
        oos=["Full themeable component library", "Window chrome / titlebar tinting"],
        wave=1, area="ui", size="S", fleet="ready",
    ),
    105: dict(
        goal="A toggle for compact vs. expanded drop-window modes — compact shows just the icon, expanded shows the full status copy.",
        files=[
            "Sources/MarkitdownUI/Controllers/DropWindowController.swift",
            "Sources/MarkitdownUI/Views/DropZoneView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.dropWindowMode`)",
        ],
        accept=[
            "Switching modes resizes the window with a brief animation and persists across launches.",
            "Compact mode keeps the drop target functional and accessible.",
            "Mode is exposed both in Preferences and via a right-click menu on the window.",
            "`swift test --verbose` passes; cover the persistence round-trip.",
        ],
        oos=["A separate “mini player”-style HUD overlay", "Per-monitor positioning"],
        wave=1, area="ui", size="S", fleet="ready",
    ),
    106: dict(
        goal="A statistics dashboard showing total conversions, format breakdown, time saved, biggest file, and streaks.",
        files=[
            "Sources/MarkitdownUI/ViewModels/ConversionManager.swift (record per-conversion metadata)",
            "Sources/MarkitdownUI/Views/ (new StatsView.swift)",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare new aggregate keys)",
        ],
        accept=[
            "Stats window opens from the menu bar item.",
            "Counts persist across launches and survive an app upgrade.",
            "Stats are cleared via an explicit “Reset stats” button.",
            "`swift test --verbose` passes; unit-test the aggregate update logic.",
        ],
        oos=["Charts beyond simple bar/sparkline", "Cloud sync (#121)"],
        wave=1, area="ui", size="M", fleet="ready",
    ),
    108: dict(
        goal="Localize all user-facing strings into es, fr, de, ja, pt-BR.",
        files=[
            "Sources/MarkitdownUI/Views/*.swift (wrap strings in `String(localized:)`)",
            "Sources/MarkitdownUI/Controllers/*.swift",
            "Sources/MarkitdownUI/Resources/ (Localizable.xcstrings)",
        ],
        accept=[
            "Every visible string is wrapped in `String(localized:)` with a stable key.",
            "An `.xcstrings` catalog is added with translations for the five target locales.",
            "Joy strings (celebrations, error quips, milestones, VoiceOver) are translated with comments preserving tone.",
            "`swift test --verbose` passes; add a test that asserts no hard-coded English remains in DropZoneView.",
        ],
        oos=["RTL layout polish", "Translation for in-progress beta features behind flags"],
        wave=1, area="ui", size="M", fleet="ready",
    ),
    109: dict(
        goal="Full keyboard navigation for the drop window: ⌘O to open file picker, Tab/Return to navigate and trigger conversion, Esc to close.",
        files=[
            "Sources/MarkitdownUI/Controllers/DropWindowController.swift",
            "Sources/MarkitdownUI/Views/DropZoneView.swift",
        ],
        accept=[
            "All actions reachable via mouse are reachable via keyboard.",
            "⌘O presents `NSOpenPanel`; selected files run through the same conversion path as drag-drop.",
            "Focus ring is visible and follows macOS keyboard-control settings.",
            "`swift test --verbose` passes; add a unit test that the menu shortcut maps to the open-panel action.",
        ],
        oos=["Customizable keyboard shortcuts (handled in #93)"],
        wave=1, area="ui", size="S", fleet="ready",
    ),
    110: dict(
        goal="A reduced-motion mode that disables confetti, Vortex, and non-essential animations.",
        files=[
            "Sources/MarkitdownUI/Views/DropZoneView.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.reducedMotion`)",
        ],
        accept=[
            "Preferences exposes the toggle; default reads `NSWorkspace.shared.accessibilityDisplayShouldReduceMotion` once.",
            "Confetti/Vortex are skipped when the toggle is on.",
            "Essential progress indicators (spinner) remain.",
            "`swift test --verbose` passes; cover both branches in a unit test.",
        ],
        oos=["Disabling sound (already #102)", "Per-animation fine-grained controls"],
        wave=1, area="ui", size="S", fleet="ready",
    ),
    125: dict(
        goal="After an in-app update, automatically show a release-notes popover anchored to the menu-bar icon.",
        files=[
            "Sources/MarkitdownUI/Controllers/StatusBarController.swift",
            "Sources/MarkitdownUI/Views/ (new ReleaseNotesView.swift)",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.lastSeenVersion`)",
        ],
        accept=[
            "On launch, if `CFBundleShortVersionString` differs from the persisted last-seen value, the popover is shown once.",
            "Notes are loaded from a bundled `RELEASE_NOTES.md` at the app root.",
            "Closing the popover updates the persisted value.",
            "`swift test --verbose` passes; cover the version-comparison logic.",
        ],
        oos=["Fetching notes from the network (handled by Sparkle in #123)"],
        wave=1, area="ui", size="S", fleet="ready",
    ),

    # ---------------- Wave 2 — Settings & profiles foundation ----------------
    117: dict(
        goal="“Profiles / presets” — save bundles of conversion options (e.g. “Obsidian Import”, “Engineering Notes”) and switch between them quickly.",
        files=[
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (model + new key `settings.profiles` and `settings.activeProfile`)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift (manage profiles)",
            "Sources/MarkitdownUI/Controllers/StatusBarController.swift (quick-switch menu)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift (apply active profile to invocation)",
        ],
        accept=[
            "Profile schema defined as a `Codable Sendable` struct with versioning for migration.",
            "Built-in “Default” profile is non-deletable; user can clone, rename, edit, delete others.",
            "Active profile is reflected in the menu-bar quick-switch and used by the conversion pipeline.",
            "`swift test --verbose` passes; cover encode/decode round-trip and active-profile fallback.",
        ],
        oos=["Profile import/export to file (separate follow-up)", "Per-format defaults (#118)"],
        wave=2, area="settings", size="L", fleet="needs-spec",
    ),
    118: dict(
        goal="Map each input file extension to a default profile so dropped files automatically use the right preset.",
        files=[
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.profileByExtension`)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
        ],
        accept=[
            "Preferences exposes a table that maps extension → profile.",
            "Drop pipeline looks up the mapping and applies the resolved profile per file.",
            "Unknown extensions fall back to the active profile.",
            "`swift test --verbose` passes; cover the extension-to-profile resolution.",
        ],
        oos=["MIME-type-based detection (extensions only)"],
        wave=2, area="settings", size="M", fleet="blocked", blocked_by=[117],
    ),
    66: dict(
        goal="Per-format options panel (PDF: OCR fallback, page range; DOCX: include comments; XLSX: sheet selection).",
        files=[
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift (translate options into CLI flags)",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.formatOptions`)",
        ],
        accept=[
            "A new “Formats” section appears with one tab per supported format.",
            "Options are stored per-profile (depends on #117).",
            "Conversion service translates the active set of options into the correct CLI args.",
            "`swift test --verbose` passes; unit-test the option → arg mapping.",
        ],
        oos=["Implementing options the bundled CLI doesn’t already support"],
        wave=2, area="settings", size="M", fleet="needs-spec", blocked_by=[117],
    ),
    92: dict(
        goal="Drop history — recent conversions list in the menu bar with “Reveal in Finder” and “Reconvert with new options.”",
        files=[
            "Sources/MarkitdownUI/Controllers/StatusBarController.swift",
            "Sources/MarkitdownUI/ViewModels/ConversionManager.swift (record history)",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.recentConversions`)",
        ],
        accept=[
            "Last N (default 10) conversions appear in the menu with input → output paths.",
            "“Reveal in Finder” opens the output; “Reconvert…” re-runs with a chosen profile (#117).",
            "Entries that point to deleted files are pruned automatically.",
            "`swift test --verbose` passes; cover the prune-on-missing behavior.",
        ],
        oos=["Persistent searchable history database"],
        wave=2, area="ui", size="M", fleet="blocked", blocked_by=[117],
    ),

    # ---------------- Wave 3 — Output destinations ----------------
    72: dict(
        goal="Configurable output naming with a token template (`{name}`, `{date}`, `{ext}`).",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.outputNameTemplate`)",
        ],
        accept=[
            "Default template preserves today’s rule: `foo.pdf` → `foo.pdf.md`.",
            "Tokens `{name}`, `{date}`, `{ext}` are substituted; collision suffix ` (1)`, ` (2)` is preserved.",
            "Invalid templates fall back to default with a non-blocking warning.",
            "`swift test --verbose` passes; cover all token substitutions and the collision suffix.",
        ],
        oos=["Per-format templates (handled later)", "Renaming existing files retroactively"],
        wave=3, area="settings", size="M", fleet="needs-spec",
    ),
    73: dict(
        goal="Choose where converted files land: same dir (current default), a chosen folder, iCloud Drive, or “ask each time.”",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.outputDestination`)",
            "MarkyMarkdown.entitlements (security-scoped bookmarks for the chosen folder)",
        ],
        accept=[
            "Default behavior is unchanged (same dir as input).",
            "Choosing a folder uses a security-scoped bookmark and survives relaunch.",
            "“Ask each time” presents `NSSavePanel` per drop.",
            "`swift test --verbose` passes; cover the destination resolution logic.",
        ],
        oos=["Cloud-provider-specific UIs beyond the standard iCloud Drive folder"],
        wave=3, area="settings", size="M", fleet="needs-spec",
    ),
    74: dict(
        goal="After conversion, optionally open the result in Obsidian / Bear / iA Writer / VS Code / Typora via URL schemes.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.openInApp`)",
        ],
        accept=[
            "Preferences offers a dropdown of supported targets plus “None.”",
            "Selected target receives the output via its documented URL scheme.",
            "Unavailable targets are gracefully skipped with a one-line user message.",
            "`swift test --verbose` passes; unit-test URL construction for each supported app.",
        ],
        oos=["Two-way sync with the editor", "Custom user-defined URL templates"],
        wave=3, area="settings", size="M", fleet="ready",
    ),
    75: dict(
        goal="Add a “Copy to clipboard” option that, instead of (or in addition to) writing a file, places the Markdown on the pasteboard.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.clipboardOutputMode`)",
        ],
        accept=[
            "Three modes available: file only (default), clipboard only, both.",
            "Clipboard write uses `NSPasteboard.general` with `.string` type.",
            "Success state surfaces a toast confirming clipboard write.",
            "`swift test --verbose` passes; cover the clipboard branch with a fake pasteboard.",
        ],
        oos=["Multi-item clipboard history"],
        wave=3, area="cli", size="S", fleet="ready",
    ),
    76: dict(
        goal="Append/merge mode — combine multiple dropped files into a single Markdown document with `---` or H1 separators.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/DropZoneView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.mergeMode`)",
        ],
        accept=[
            "When enabled, a multi-file drop produces one combined `.md` (named after the first file) following the output naming rule.",
            "Separator style (rule vs. heading) is user-selectable; default is `---`.",
            "Per-file errors don’t abort the merge; failures are listed at the end of the doc.",
            "`swift test --verbose` passes; cover the merge ordering and error-tail behavior.",
        ],
        oos=["Re-ordering files via drag inside the drop window"],
        wave=3, area="cli", size="M", fleet="ready",
    ),
    113: dict(
        goal="“Dry run” mode — show the user what would be written without touching the disk.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.dryRun`)",
        ],
        accept=[
            "When enabled, conversion runs but no file is written; result is shown in a sheet/preview.",
            "A clear visual indicator (badge) is on the menu bar while dry-run is active.",
            "`swift test --verbose` passes; cover that no file IO occurs in dry-run mode.",
        ],
        oos=["Diff vs. existing file (covered by #82)"],
        wave=3, area="settings", size="S", fleet="ready",
    ),
    84: dict(
        goal="A quick preview window that opens immediately after conversion with a “Save / Discard / Edit” toolbar.",
        files=[
            "Sources/MarkitdownUI/Controllers/ (new PreviewWindowController.swift)",
            "Sources/MarkitdownUI/Views/ (new PreviewView.swift)",
            "Sources/MarkitdownUI/ViewModels/ConversionManager.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.showPreviewAfterConversion`)",
        ],
        accept=[
            "When enabled, conversion holds the write until the user hits “Save” in the preview.",
            "“Discard” deletes any pending output; “Edit” opens in the configured editor (#74).",
            "Preview renders Markdown with WebKit + GitHub-flavored CSS.",
            "`swift test --verbose` passes; cover the “discard never writes” invariant.",
        ],
        oos=["Editing inside the preview window itself"],
        wave=3, area="ui", size="M", fleet="ready",
    ),
    82: dict(
        goal="A diff view for cases where the output filename collides with an existing `.md` — show source vs. resulting Markdown side-by-side before saving.",
        files=[
            "Sources/MarkitdownUI/Controllers/ (new DiffWindowController.swift)",
            "Sources/MarkitdownUI/Views/ (new DiffView.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
        ],
        accept=[
            "When the output path already exists, present a side-by-side diff and a Save / Cancel choice.",
            "Choosing Save still respects the collision-suffix rule if the user picks “Keep both.”",
            "Reuses the preview rendering from #84 where possible.",
            "`swift test --verbose` passes; cover the collision branch.",
        ],
        oos=["Three-way merge", "In-place editing of the diff"],
        wave=3, area="ui", size="M", fleet="blocked", blocked_by=[84],
    ),

    # ---------------- Wave 4 — System integration extensions ----------------
    85: dict(
        goal="A Quick Look extension so any `.md` file in Finder previews with proper rendering.",
        files=[
            "Package.swift (new target / app extension)",
            "Sources/ (new MarkdownQuickLook/ extension target)",
            "build-dmg.sh (bundle the extension into the app)",
        ],
        accept=[
            "Quick-Looking a `.md` shows rendered Markdown (GitHub-flavored CSS), not raw text.",
            "Extension is sandboxed and signed under the same team ID as the host app.",
            "`swift test --verbose` passes for the host app and the extension.",
        ],
        oos=["Editing inside Quick Look", "Image inlining beyond what WebKit handles"],
        wave=4, area="packaging", size="M", fleet="ready",
    ),
    86: dict(
        goal="A Finder Quick Action / Service: right-click any file → “Convert to Markdown with MarkyMarkdown.”",
        files=[
            "Package.swift (new app extension)",
            "Sources/ (new MarkyFinderService/ extension target)",
            "build-dmg.sh",
        ],
        accept=[
            "Selected file(s) launch the converter via the existing pipeline; no new conversion logic introduced.",
            "Service is registered for all UTIs supported by the bundled CLI.",
            "`swift test --verbose` passes.",
        ],
        oos=["A separate batch-management UI"],
        wave=4, area="packaging", size="M", fleet="ready",
    ),
    87: dict(
        goal="A macOS Share extension so MarkyMarkdown appears in the Share menu from Safari, Mail, Preview, etc.",
        files=[
            "Package.swift",
            "Sources/ (new MarkyShareExtension/ target)",
            "build-dmg.sh",
        ],
        accept=[
            "Sharing a URL or file from Safari/Preview produces the same `.md` output as drag-drop.",
            "Extension reads/writes through the same conversion service used by the app.",
            "`swift test --verbose` passes.",
        ],
        oos=["Sharing the resulting Markdown back out to other apps in one step"],
        wave=4, area="packaging", size="M", fleet="ready",
    ),
    89: dict(
        goal="Expose Shortcuts.app actions: “Convert File,” “Convert URL,” “Convert Clipboard.”",
        files=[
            "Package.swift",
            "Sources/MarkitdownUI/ (AppIntents implementation)",
            "MarkyMarkdown.entitlements (App Intents capability)",
        ],
        accept=[
            "Three intents are registered and discoverable in the Shortcuts app.",
            "Each intent returns the resulting Markdown text and the output file path.",
            "Intents reuse the conversion service; no duplicated CLI logic.",
            "`swift test --verbose` passes; cover intent input/output marshaling.",
        ],
        oos=["Custom intent UIs beyond stock parameter prompts"],
        wave=4, area="packaging", size="M", fleet="ready",
    ),
    90: dict(
        goal="Install a `marky` shim into `/usr/local/bin` (with user consent) that calls the bundled `markitdown` CLI from the terminal.",
        files=[
            "Sources/MarkitdownUI/Controllers/ (new CLIInstallController.swift)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/Resources/marky (new shim script)",
        ],
        accept=[
            "Preferences exposes “Install/Uninstall command-line tool.”",
            "Install uses an authorized helper; uninstall removes the shim cleanly.",
            "Shim resolves the bundled binary via `Bundle.main.resourcePath` semantics; never hard-codes a user path.",
            "`swift test --verbose` passes; cover the path-resolution logic with a fake bundle.",
        ],
        oos=["Auto-updating the shim when the app moves"],
        wave=4, area="cli", size="S", fleet="ready",
    ),
    91: dict(
        goal="AppleScript / JXA support for power users (convert files, query stats, switch profiles).",
        files=[
            "Sources/MarkitdownUI/AppDelegate.swift (Scripting bridge)",
            "Sources/MarkitdownUI/Resources/ (sdef file)",
        ],
        accept=[
            "An sdef defines `convert`, `currentProfile`, and `statistics` commands.",
            "Each scripting command goes through the same conversion service.",
            "`swift test --verbose` passes; unit-test the scripting handlers via in-process invocation.",
        ],
        oos=["Custom scripting UI"],
        wave=4, area="cli", size="M", fleet="ready",
    ),
    93: dict(
        goal="A user-configurable global hotkey to open the drop window or convert the current Finder selection.",
        files=[
            "Sources/MarkitdownUI/Controllers/StatusBarController.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.globalHotkey`)",
        ],
        accept=[
            "Preferences offers a hotkey recorder; default is unset.",
            "Hotkey works while the app is in the background; conflicts surface a non-blocking warning.",
            "If a Finder selection exists, it’s converted; otherwise the drop window is shown.",
            "`swift test --verbose` passes; cover the hotkey serialization.",
        ],
        oos=["Multiple hotkeys", "Per-profile hotkeys"],
        wave=4, area="ui", size="M", fleet="ready",
    ),

    # ---------------- Wave 5 — Conversion power-ups ----------------
    64: dict(
        goal="Drop a folder and recursively convert every supported file inside, preserving structure.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/DropZoneView.swift",
            "Sources/MarkitdownUI/ViewModels/ConversionManager.swift",
        ],
        accept=[
            "Dropping a folder enumerates files (respecting `.gitignore`-style hidden-file rules).",
            "Output mirrors the source tree under either same-dir-with-suffix or the destination from #73.",
            "Per-file errors are surfaced individually and don’t abort the batch.",
            "`swift test --verbose` passes; cover enumeration order and error isolation.",
        ],
        oos=["Parallel conversion limits / scheduling UI"],
        wave=5, area="cli", size="L", fleet="ready",
    ),
    65: dict(
        goal="Watch folders — designate folders that auto-convert any new file dropped in.",
        files=[
            "Sources/MarkitdownUI/Services/ (new FolderWatcher.swift, NSFilePresenter / FSEvents-based)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.watchedFolders`)",
        ],
        accept=[
            "User can add/remove watched folders via Preferences (security-scoped bookmarks persisted).",
            "New files trigger conversion exactly once, with debouncing to avoid partial-write reads.",
            "Watcher pauses cleanly on app sleep/quit; resumes on launch.",
            "`swift test --verbose` passes; cover the debounce and dedup logic.",
        ],
        oos=["Glob patterns / per-folder profile mapping"],
        wave=5, area="cli", size="M", fleet="ready",
    ),
    67: dict(
        goal="OCR fallback for image-only PDFs and screenshots using Apple Vision when the bundled CLI returns empty text.",
        files=[
            "Sources/MarkitdownUI/Services/ (new VisionOCRService.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.ocrFallbackEnabled`)",
        ],
        accept=[
            "When CLI output for a PDF/image is empty/whitespace, Vision is invoked and its text is returned as Markdown.",
            "Toggle defaults to ON for images, OFF for PDFs; both are user-configurable.",
            "OCR runs on-device; no network calls.",
            "`swift test --verbose` passes; cover the “empty CLI output → Vision invoked” branch with a stub.",
        ],
        oos=["Layout reconstruction (paragraph order is best-effort)"],
        wave=5, area="cli", size="M", fleet="ready",
    ),
    68: dict(
        goal="Audio/video transcription: convert `.mp3`, `.m4a`, `.mp4` to Markdown transcripts (with timestamps) using Apple’s on-device Speech framework.",
        files=[
            "Sources/MarkitdownUI/Services/ (new SpeechTranscriptionService.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "MarkyMarkdown.entitlements (Speech recognition usage)",
        ],
        accept=[
            "Drag of a supported audio/video file produces a `.md` with timestamped paragraphs.",
            "Transcription runs on-device; user is prompted for permission once.",
            "Long files chunk into segments; partial progress is shown.",
            "`swift test --verbose` passes; cover the chunking logic with a fake recognizer.",
        ],
        oos=["Speaker diarization", "Live mic capture"],
        wave=5, area="cli", size="L", fleet="needs-spec",
    ),
    69: dict(
        goal="URL → Markdown: paste a URL or drop a `.webloc` to fetch and convert web pages, YouTube transcripts, GitHub READMEs, arXiv PDFs.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/DropZoneView.swift (accept text/URL drags)",
            "Sources/MarkitdownUI/Controllers/StatusBarController.swift (menu item)",
        ],
        accept=[
            "Pasting a URL into the drop window or menu triggers a fetch + convert.",
            "`.webloc` files extract the URL and route through the same path.",
            "Network failures produce a playful, actionable error (use `playfulErrorMessage(_:)`).",
            "`swift test --verbose` passes; cover the URL extraction from `.webloc`.",
        ],
        oos=["Authenticated sites / cookie management"],
        wave=5, area="cli", size="M", fleet="ready",
    ),
    70: dict(
        goal="A menu-bar item that converts the current clipboard contents (HTML, RTF, image) into Markdown.",
        files=[
            "Sources/MarkitdownUI/Controllers/StatusBarController.swift",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
        ],
        accept=[
            "Menu item “Convert clipboard” detects HTML / RTF / image and routes appropriately.",
            "Output respects the clipboard-output-mode setting from #75.",
            "Disabled state when clipboard is empty or unsupported.",
            "`swift test --verbose` passes; cover the type-detection branches with a fake pasteboard.",
        ],
        oos=["Continuous clipboard monitoring"],
        wave=5, area="cli", size="M", fleet="ready",
    ),
    78: dict(
        goal="An optional post-processing pipeline: prettify tables, normalize whitespace, demote headings, strip emoji, smart-quote conversion, or pipe through Prettier.",
        files=[
            "Sources/MarkitdownUI/Services/ (new MarkdownPostProcessor.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
        ],
        accept=[
            "Each pass is independently toggleable and stored on the active profile (#117).",
            "Passes are pure functions on `String` and composable in a fixed order.",
            "Prettier pass is optional, requires a user-installed Prettier, and is skipped gracefully if missing.",
            "`swift test --verbose` passes; cover each built-in pass with golden fixtures.",
        ],
        oos=["Building Prettier into the app bundle"],
        wave=5, area="cli", size="L", fleet="needs-spec", blocked_by=[117],
    ),
    79: dict(
        goal="Inject YAML frontmatter (title, source path, conversion date, original size, checksum) at the top of every `.md`.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.frontmatterEnabled`)",
        ],
        accept=[
            "Toggle defaults to OFF; when ON, frontmatter is injected.",
            "Field set is user-configurable; values are deterministic for a given input.",
            "Existing frontmatter in the converted output is detected and merged, not duplicated.",
            "`swift test --verbose` passes; cover injection and merge cases.",
        ],
        oos=["User-defined arbitrary keys beyond the documented set (initial scope)"],
        wave=5, area="cli", size="S", fleet="ready",
    ),
    80: dict(
        goal="Choose the image-extraction strategy: embed as data URIs (current), extract to a sibling `assets/` folder with relative links, or upload to a configured image host.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift (post-pass)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.imageStrategy`)",
        ],
        accept=[
            "Default behavior matches today (data URIs, controlled by `settings.keepDataURIs`).",
            "“Extract” mode writes to `<output>.assets/` and rewrites image links relatively.",
            "Image-host upload is feature-flagged behind a needs-spec follow-up; not shipped in this issue.",
            "`swift test --verbose` passes; cover the extract-mode link rewriting.",
        ],
        oos=["Implementing the upload path", "Re-deduplicating images across files"],
        wave=5, area="cli", size="L", fleet="needs-spec",
    ),
    81: dict(
        goal="Rewrite relative links in source HTML/DOCX to repo-relative or absolute URLs in the resulting Markdown.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift (post-pass)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.linkRewriteMode`)",
        ],
        accept=[
            "Three modes: leave-as-is (default), repo-relative, absolute (using a user-supplied base URL).",
            "Anchors and mailto links are untouched.",
            "Rewriting never changes the link text, only the URL.",
            "`swift test --verbose` passes; cover each mode with a golden fixture.",
        ],
        oos=["Validating that the rewritten URLs resolve"],
        wave=5, area="cli", size="M", fleet="ready",
    ),
    96: dict(
        goal="Auto-derive frontmatter `title` and `tags` from converted content using on-device intelligence.",
        files=[
            "Sources/MarkitdownUI/Services/ (new ContentAnalysisService.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.autoTagEnabled`)",
        ],
        accept=[
            "Title is derived from the first H1 / first non-empty line / filename, in that order.",
            "Tags are derived via NaturalLanguage tokenization (no network).",
            "Output integrates with #79 frontmatter injection; never duplicates fields.",
            "`swift test --verbose` passes; golden fixtures for title derivation precedence.",
        ],
        oos=["LLM-driven tagging (handled in #95/#97)"],
        wave=5, area="ai", size="M", fleet="needs-spec", blocked_by=[79],
    ),
    98: dict(
        goal="Smart cleanup pass for messy PDF tables: detect table-shaped runs of text and emit valid GFM tables.",
        files=[
            "Sources/MarkitdownUI/Services/ (new TableCleanupService.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
        ],
        accept=[
            "Heuristic uses column alignment and row consistency; runs after the bundled CLI.",
            "Pass is conservative — never destroys content it can’t confidently restructure.",
            "`swift test --verbose` passes; cover at least three real-world PDF table fixtures.",
        ],
        oos=["Image-of-table OCR (Vision is #67)"],
        wave=5, area="ai", size="M", fleet="needs-spec",
    ),
    119: dict(
        goal="Pandoc fallback for formats MarkItDown handles poorly (epub, org-mode, LaTeX), shelling out to a user-installed Pandoc.",
        files=[
            "Sources/MarkitdownUI/Services/ (new PandocService.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.pandocPath`)",
        ],
        accept=[
            "Detects Pandoc on PATH; user can override the path in Preferences.",
            "Triggered only for the documented fallback formats.",
            "Absent Pandoc → friendly error pointing to install instructions.",
            "`swift test --verbose` passes; cover the routing decision.",
        ],
        oos=["Bundling Pandoc inside the app"],
        wave=5, area="cli", size="M", fleet="needs-spec",
    ),

    # ---------------- Wave 6 — Distribution, trust, AI ----------------
    95: dict(
        goal="Auto-summarize: generate a TL;DR section at the top of the converted Markdown via Apple Foundation Models on macOS 15+.",
        files=[
            "Sources/MarkitdownUI/Services/ (new SummarizationService.swift, gated to macOS 15+)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.summarizeEnabled`)",
        ],
        accept=[
            "Disabled by default; only available on macOS 15+ at runtime.",
            "Summary is on-device; no network calls.",
            "Output integrates with #79 frontmatter without duplication.",
            "`swift test --verbose` passes; OS-gated tests are skipped cleanly on older macOS.",
        ],
        oos=["Cloud-LLM fallbacks", "Per-section summaries"],
        wave=6, area="ai", size="L", fleet="needs-spec", blocked_by=[79],
    ),
    97: dict(
        goal="Translate-to-Markdown: convert and translate the result into a user-chosen language in one pass.",
        files=[
            "Sources/MarkitdownUI/Services/ (new TranslationService.swift, on-device Translation framework)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.translateTarget`)",
        ],
        accept=[
            "Disabled by default; OS-gated to versions where the on-device Translation framework is available.",
            "Code blocks, links, and frontmatter values are preserved untranslated.",
            "Failures fall back to the untranslated Markdown.",
            "`swift test --verbose` passes; cover the preserve-codeblock invariant.",
        ],
        oos=["Cloud translation providers"],
        wave=6, area="ai", size="L", fleet="needs-spec",
    ),
    112: dict(
        goal="Sandboxed file-scope notifications — clear in-app messaging about exactly what files MarkyMarkdown read or wrote.",
        files=[
            "Sources/MarkitdownUI/Views/ (new FileScopeBanner.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift (emit events)",
            "Sources/MarkitdownUI/ViewModels/ConversionManager.swift",
        ],
        accept=[
            "After each conversion, a transient banner lists each file path touched.",
            "Banner is screen-reader friendly and dismissible.",
            "No paths leave the device.",
            "`swift test --verbose` passes; cover the “read + write paths recorded” invariant.",
        ],
        oos=["A persistent audit log (handled by #114)"],
        wave=6, area="ui", size="S", fleet="ready",
    ),
    114: dict(
        goal="A conversion log / activity panel with redact-friendly export for bug reports.",
        files=[
            "Sources/MarkitdownUI/Views/ (new ActivityLogView.swift)",
            "Sources/MarkitdownUI/ViewModels/ (new ActivityLogStore.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
        ],
        accept=[
            "Per-conversion entries record: timestamp, status, profile, duration, anonymized path.",
            "Export produces a markdown file with paths redacted to basenames.",
            "Log capped at N entries; older entries pruned.",
            "`swift test --verbose` passes; cover redaction and prune logic.",
        ],
        oos=["Remote log shipping"],
        wave=6, area="ui", size="M", fleet="ready",
    ),
    115: dict(
        goal="Compute and record SHA-256 checksums of input and output for archival reproducibility.",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.recordChecksums`)",
        ],
        accept=[
            "Toggle defaults to OFF; when ON, checksums are written to the frontmatter (#79) and the activity log (#114).",
            "Algorithm is SHA-256 via CryptoKit.",
            "`swift test --verbose` passes; cover checksum determinism for a fixed fixture.",
        ],
        oos=["Signing or verifying checksums"],
        wave=6, area="cli", size="S", fleet="ready", blocked_by=[79, 114],
    ),
    120: dict(
        goal="Run a user-provided shell script before each conversion (input hook) and/or after (output hook).",
        files=[
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.preScriptPath`, `settings.postScriptPath`)",
        ],
        accept=[
            "Scripts receive the input path / output path via env vars; non-zero exit aborts the conversion with a clear error.",
            "Scripts run inside the app sandbox’s allowed scope; absolute paths only.",
            "User is warned the first time a script is configured (security implications).",
            "`swift test --verbose` passes; cover the abort-on-non-zero-exit branch.",
        ],
        oos=["Inline script editor"],
        wave=6, area="cli", size="M", fleet="needs-spec",
    ),
    121: dict(
        goal="Sync MarkyMarkdown settings (and only settings) across the user’s Macs via iCloud.",
        files=[
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift",
            "MarkyMarkdown.entitlements (CloudKit / NSUbiquitousKeyValueStore)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
        ],
        accept=[
            "Optional toggle in Preferences; defaults to OFF.",
            "Only the four documented UserDefaults keys (and any new ones declared in `AppSettingsStore.swift`) are synced.",
            "Conflicts use last-writer-wins.",
            "`swift test --verbose` passes; cover the “sync respects only allowed keys” invariant.",
        ],
        oos=["Syncing profiles, history, or stats (separate follow-up)"],
        wave=6, area="settings", size="M", fleet="needs-spec",
    ),
    123: dict(
        goal="Sparkle auto-update with a public appcast served from the GitHub Pages site.",
        files=[
            "Package.swift (Sparkle SPM)",
            "Sources/MarkitdownUI/AppDelegate.swift (SPUStandardUpdaterController)",
            "Sources/MarkitdownUI/Resources/Info.plist additions (SUFeedURL, SUPublicEDKey)",
            ".github/workflows/release.yml (publish appcast)",
        ],
        accept=[
            "App checks for updates on launch (rate-limited) and via Preferences.",
            "Release workflow publishes a signed appcast item per tagged release.",
            "EdDSA public key is embedded; signing key never leaves CI secrets.",
            "`swift test --verbose` passes.",
        ],
        oos=["Delta updates", "Beta channel"],
        wave=6, area="packaging", size="L", fleet="needs-spec",
    ),
    124: dict(
        goal="Publish a Homebrew cask so users can `brew install --cask markymarkdown`.",
        files=[
            ".github/workflows/release.yml (open PR to homebrew-cask on tag)",
            "docs/INSTALL.md (mention the cask)",
            "README.md (install snippet)",
        ],
        accept=[
            "Cask formula is added to a tap or upstream homebrew-cask, pointing at the signed/notarized DMG asset.",
            "SHA256 is computed in CI and templated into the cask.",
            "Release workflow opens the cask PR automatically (or documents a one-command manual flow if upstream blocks bots).",
            "`swift test --verbose` is unaffected.",
        ],
        oos=["A custom tap as the primary distribution channel"],
        wave=6, area="packaging", size="S", fleet="ready", blocked_by=[123],
    ),
    126: dict(
        goal="Optional, opt-in crash reporting via a privacy-friendly provider (e.g. Sentry self-hosted) — disabled by default.",
        files=[
            "Package.swift (provider SDK)",
            "Sources/MarkitdownUI/AppDelegate.swift (initialize only when opted in)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.crashReportingEnabled`)",
        ],
        accept=[
            "First launch shows an explicit, opt-in dialog; default is OFF.",
            "When OFF, no SDK code paths execute and no network calls are made.",
            "PII (file paths, clipboard, content) is never sent.",
            "`swift test --verbose` passes; cover the opt-out invariant.",
        ],
        oos=["Telemetry beyond crashes"],
        wave=6, area="packaging", size="M", fleet="needs-spec",
    ),
    128: dict(
        goal="A plugin API: users register custom converters or post-processors via Swift bundles or shell scripts in `~/Library/Application Support/MarkyMarkdown/plugins/`.",
        files=[
            "Sources/MarkitdownUI/Services/ (new PluginLoader.swift)",
            "Sources/MarkitdownUI/Services/MarkitdownConversionService.swift",
            "docs/ (new PLUGINS.md describing the contract)",
        ],
        accept=[
            "Plugins discovered at app launch; failures are isolated and logged.",
            "Plugins declare supported UTIs; conflicts use a documented precedence rule.",
            "Plugin scripts run sandboxed via XPC where available.",
            "`swift test --verbose` passes; cover discovery and isolation with a fake plugin dir.",
        ],
        oos=["A plugin marketplace / signing infrastructure"],
        wave=6, area="cli", size="L", fleet="needs-spec",
    ),
    129: dict(
        goal="Webhook / “send to” integrations — POST converted Markdown to a configured endpoint (Notion, GitHub Gist, Linear, a personal API).",
        files=[
            "Sources/MarkitdownUI/Services/ (new WebhookService.swift)",
            "Sources/MarkitdownUI/Views/PreferencesView.swift",
            "Sources/MarkitdownUI/ViewModels/AppSettingsStore.swift (declare `settings.webhooks`)",
        ],
        accept=[
            "Webhook configs (URL, method, headers, body template) are stored in the Keychain, not UserDefaults, when secrets are present.",
            "Per-webhook enable/disable toggle; default is no webhooks configured.",
            "Failures surface a non-blocking notification with the response code.",
            "`swift test --verbose` passes; cover the body templating with golden fixtures.",
        ],
        oos=["First-class OAuth flows for specific providers"],
        wave=6, area="settings", size="L", fleet="needs-spec",
    ),
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_prd(num: int, data: dict) -> str:
    lines: list[str] = []
    lines.append(PRD_MARKER)
    lines.append("")
    lines.append("# PRD")
    lines.append("")
    lines.append("## Goal")
    lines.append(data["goal"])
    lines.append("")
    lines.append("## Files likely to change")
    for f in data["files"]:
        # Allow entries of the form "path (annotation)" — render the path in
        # backticks and the annotation as prose so it doesn't read like part
        # of the path itself.
        path, sep, note = f.partition(" (")
        if sep and note.endswith(")"):
            lines.append(f"- `{path}` — {note[:-1]}")
        else:
            lines.append(f"- `{f}`")
    lines.append("")
    lines.append("## Acceptance criteria")
    for a in data["accept"]:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("## Out of scope")
    for o in data["oos"]:
        lines.append(f"- {o}")
    lines.append("")
    lines.append("## Routing")
    lines.append(f"- Wave: **{data['wave']}**")
    lines.append(f"- Area: **{data['area']}**")
    lines.append(f"- Size: **{data['size']}**")
    lines.append(f"- Fleet status: **{data['fleet']}**")
    if data.get("blocked_by"):
        deps = ", ".join(f"#{n}" for n in data["blocked_by"])
        lines.append(f"- Blocked by: {deps}")
    lines.append("")
    lines.append(CONVENTIONS)
    return "\n".join(lines)


def labels_for(data: dict) -> list[str]:
    out = [
        f"fleet:{data['fleet']}",
        f"size:{data['size']}",
        f"area:{data['area']}",
        f"wave:{data['wave']}",
    ]
    if data.get("blocked_by") and data["fleet"] != "blocked":
        out.append("fleet:blocked")
    return out


# ---------------------------------------------------------------------------
# gh helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], *, dry: bool, capture: bool = False) -> Optional[str]:
    printable = " ".join(shlex.quote(c) for c in cmd)
    if dry:
        print(f"[dry-run] {printable}")
        return None
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"command failed: {printable}\n")
        if result.stderr:
            sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    return result.stdout if capture else None


def ensure_labels(dry: bool) -> None:
    print(f"=== Ensuring {len(LABELS)} routing labels ===")
    for name, color, desc in LABELS:
        # `gh label create --force` updates color/description if it already exists.
        run(
            [
                "gh", "label", "create", name,
                "--repo", REPO,
                "--color", color,
                "--description", desc,
                "--force",
            ],
            dry=dry,
        )


def get_issue_body(num: int) -> str:
    out = subprocess.run(
        ["gh", "issue", "view", str(num), "--repo", REPO, "--json", "body"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out).get("body") or ""


def update_issue(num: int, data: dict, *, dry: bool, force: bool) -> None:
    body = render_prd(num, data)
    labels = labels_for(data)

    if not dry and not force:
        try:
            current = get_issue_body(num)
        except subprocess.CalledProcessError:
            current = ""
        if PRD_MARKER in current:
            print(f"#{num}: PRD marker already present, skipping body (use --force to overwrite). Adding labels (existing labels not removed).")
            run(
                ["gh", "issue", "edit", str(num), "--repo", REPO,
                 "--add-label", ",".join(labels)],
                dry=dry,
            )
            return

    if dry:
        print(f"\n--- #{num} body preview (first 12 lines) ---")
        for line in body.splitlines()[:12]:
            print(f"  {line}")
        print(f"  ... ({len(body.splitlines())} lines total)")
        print(f"  labels: {labels}")
        return

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(body)
        body_file = fh.name
    try:
        run(
            [
                "gh", "issue", "edit", str(num),
                "--repo", REPO,
                "--body-file", body_file,
                "--add-label", ",".join(labels),
            ],
            dry=False,
        )
    finally:
        Path(body_file).unlink(missing_ok=True)
    print(f"#{num}: updated.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without calling gh.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite issue bodies even if a PRD marker is present.")
    parser.add_argument("--only", type=int, nargs="*",
                        help="Restrict to specific issue numbers.")
    args = parser.parse_args()

    # Sanity: assert no excluded issue snuck into ISSUES.
    overlap = EXCLUDED & set(ISSUES.keys())
    if overlap:
        sys.stderr.write(f"ERROR: excluded issues present in ISSUES dict: {sorted(overlap)}\n")
        return 2

    print(f"Repo: {REPO}")
    print(f"Issues to seed: {len(ISSUES)}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}{' (force)' if args.force else ''}\n")

    ensure_labels(dry=args.dry_run)

    targets = sorted(ISSUES.keys())
    if args.only:
        wanted = set(args.only)
        targets = [n for n in targets if n in wanted]

    print(f"\n=== Updating {len(targets)} issues ===")
    for num in targets:
        update_issue(num, ISSUES[num], dry=args.dry_run, force=args.force)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
