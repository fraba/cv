---
name: zotero-cv-sync
description: Sync francesco_bailo_cv.tex/.bib against the curated Zotero collections (source of truth). Use when the user asks to update/sync/refresh the CV from Zotero, or check Zotero for new publications/presentations.
---

# Zotero → CV sync

Francesco's Zotero library is the source of truth for his publication/
presentation record, but only a specific set of collections holds the
curated material meant to appear on the CV — not his whole library. The
monitored collections and which CV section each drives are listed in
`.claude/zotero-cv-sync.json` (root: `.../users/1127234/collections/HM5SIRSB`,
9 named subcollections — Peer-reviewed, Books, Book sections, Research
report, News articles, Media appearances, Presentation, Thesis, Preprint).

The `mcp__zotero__*` tools (`zotero_search_items`, `zotero_item_metadata`,
`zotero_item_fulltext`) cannot scope to a specific collection — they only
search the entire library. Do not rely on them for this task; use the
script below instead, which talks to the Zotero Web API directly and can
fetch a named collection (plus its own subcollections, recursively).

## Steps

1. **Check for the API key.** Run `echo $ZOTERO_API_KEY | head -c1` (or
   just try step 2). If unset, tell the user to create a **read-only**
   key at https://www.zotero.org/settings/keys (grant library read
   access only — no write access needed) and export it, e.g. add to
   their shell profile:
   ```
   export ZOTERO_API_KEY=...
   ```
   Do not ask them to paste the key value into the chat; have them set
   the env var directly (`! export ZOTERO_API_KEY=...` if they want it
   set for this session only). Never write the key into any file in
   this repo.

2. **Run the sync script:**
   ```
   python3 scripts/zotero_sync.py
   ```
   It prints a JSON report to stdout (nothing is written to disk). It
   uses stdlib only — no pip install needed. Fields:
   - `collections`: item count fetched per monitored collection — sanity
     check nothing is unexpectedly empty or huge.
   - `type_mismatch_items`: items whose Zotero itemType looks wrong for
     the collection they're filed under (e.g. a `journalArticle` sitting
     in the Preprint collection) — inspect these, they may indicate a
     filing mistake in Zotero rather than a CV issue.
   - `new_bib_items` (+ `new_bib_items_biblatex`, ready-to-paste BibLaTeX
     text pulled straight from the Zotero API for those items): items
     not already matched (by DOI, else normalized title) against
     `francesco_bailo_cv.bib`. Each carries `target_cv_subsection` taken
     directly from which monitored collection it came from — trust this
     over guessing from itemType alone, since Francesco does the
     News-articles-vs-Media-appearances sorting in Zotero itself.
   - `new_presentations`: Zotero `presentation`-type items (from the
     Presentation collection) not already matched (by date, else
     normalized title) against the CV's Presentations `\cventry` blocks.
     Each has `needs_venue_info: true` if Zotero's `meetingName`/`place`
     fields are empty — **do not invent a venue**; either ask the user,
     or ask them to fill in those two fields on the Zotero item and
     re-run.
   - `preprint_status`: every item in the Preprint collection, with the
     best-matching published title found (searched against both the live
     Peer-reviewed collection and already-published `.bib` entries) and
     a fuzzy-match score. `likely_superseded: true` (score ≥ 0.6) means
     the paper looks published now — **per Francesco's explicit rule,
     preprints must be dropped from the CV once the real paper is
     published**, so these are excluded from `new_bib_items`
     automatically. Still confirm with him before deleting anything
     already in the CV (see next field) — fuzzy title matching can be
     wrong, and he asked to be consulted when in doubt.
   - `stale_preprint_bib_entries_to_review`: existing `.bib` entries that
     (a) are actually cited somewhere in the CV and (b) look like an
     unpublished/preprint entry whose title now fuzzy-matches a published
     Peer-reviewed item. These are candidates to delete-and-replace with
     the published version — always ask Francesco to confirm the match
     before removing one.

3. **Never apply changes silently.** Present the new/changed/superseded
   items to the user (title, date, target section) before editing
   `francesco_bailo_cv.tex` / `.bib`. This is a curated document — when
   anything is ambiguous (a `type_mismatch_items` entry, a borderline
   `preprint_status` score, a `Thesis`-collection item with no
   established place in the CV yet — see the config file's `notes`),
   ask rather than guess, per Francesco's standing instruction.

4. **On confirmation, edit the files** following existing conventions
   (see `CLAUDE.md`): `\fullcite{key}` entries for anything bib-backed,
   full 6-argument `\cventry{date}{role}{event}{location}{}{description}`
   for presentations, reverse-chronological order, `academicons` badges
   (`\aiOpenAccess`, `\aiOpenData`, `\aiOpenMaterials`) on publications
   where applicable. For new BibLaTeX entries, prefer the Better BibTeX
   citekey if Zotero returned one (`citekey_hint` in the report /
   `Citation Key:` line in the item's Extra field) so keys stay
   consistent with the rest of the file; otherwise follow the existing
   `lastname_ShortTitle_year` convention. When replacing a stale preprint
   entry, remove both its `\fullcite{...}` line and its `.bib` entry.

5. **Update the summary stats** in the `boxH` box at the top of the
   Research section (article/book/news-article counts, presentation
   count, media-appearance count) to match the new totals.

6. **Recompile if possible**: `which lualatex biber` — if present, run
   the full build (see CLAUDE.md) to confirm it compiles; if not
   installed, say so rather than claiming it was verified.

## Config

`.claude/zotero-cv-sync.json` (committed, no secrets in it) holds the
monitored collection keys/sections, the Zotero user ID, and free-text
`notes` for open questions (e.g. the current lack of an established CV
slot for Thesis items). Edit it directly if collections are
added/renamed/removed in Zotero. The API key is never read from here —
only from the `ZOTERO_API_KEY` env var.
