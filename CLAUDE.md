# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Operating with full autonomy in this repo

Francesco has explicitly authorized proceeding **without asking for
confirmation** on any operation confined to this repository folder —
editing `.tex`/`.bib`/`.bibtex` or other files here, running the LaTeX
build, reading local files this repo's CLAUDE.md points to (e.g. the
grants folder), and git operations (`add`, `commit`, `push`) on this
repo. This is a low-stakes, single-author document repo, and the full
git history makes any change trivially reversible, so the usual
pause-and-confirm default doesn't apply here.

This does **not** extend to genuinely destructive/irreversible git
operations (`push --force`, `reset --hard`, `clean -f`, rewriting
history) — those still need explicit request — nor to actions outside
this folder (e.g. editing files in the `my-website` repo), which still
follow normal confirm-first behavior.

## Repository overview

This repo contains a single academic CV, typeset in LaTeX (`moderncv` class):

- `francesco_bailo_cv.tex` — the CV source (~1100 lines).
- `francesco_bailo_cv.bib` — BibLaTeX bibliography (biblatex/biber, APA style) referenced by `francesco_bailo_cv.tex` via `\fullcite{...}`.
- `francesco_bailo_cv.pdf` — the compiled, committed output. Regenerate and commit this whenever `.tex`/`.bib` changes so the PDF stays in sync with the source.

There is no application code, build system, package manifest, or test suite — this is a document-only repository.

## Build

The document must be compiled with **LuaLaTeX** (declared via the `% !TEX program = lualatex` magic comment on line 1) plus **biber** for the bibliography:

```bash
lualatex francesco_bailo_cv.tex
biber francesco_bailo_cv
lualatex francesco_bailo_cv.tex
lualatex francesco_bailo_cv.tex
```

(Two final `lualatex` passes are needed to resolve cross-references and the bibliography after biber runs.) `pdflatex`/`xelatex` will not work correctly — the document uses `fontspec` and `academicons`/`fontawesome5`, which require LuaLaTeX or XeLaTeX's font handling; the magic comment pins the engine to LuaLaTeX for editors/CI that respect it (e.g. latexmk, TeXShop, VS Code LaTeX Workshop).

No LaTeX toolchain (`lualatex`/`biber`) is installed in this environment by default — check with `which lualatex biber` before assuming a build is possible, and tell the user if compilation can't be verified locally.

## Document structure

The `.tex` file is organized into top-level `\section`s, in this order: **Academic positions → Non-academic positions → Education → Research → Teaching → Awards and prizes → Skills**.

The **Research** section is the largest and itself contains `\subsection`s for grants (External/Internal), **Publications** (further split into `\subsubsection`s: peer-reviewed articles, books, book sections, research reports/public submissions, news articles), **Presentations**, and **Media appearances**.

Key conventions to preserve when editing:

- **Positions/entries** use moderncv's `\cventry{dates}{title}{institution}{location}{}{description}` command — keep the 6-argument shape even when trailing fields are empty.
- **Publications** are listed with `\fullcite{<bibkey>}` (pulling from the `.bib` file) rather than hand-typed citations, followed by inline badges/links such as `{\aiOpenAccess}`, `\href{...}{\aiOpenData}`, `\href{...}{\aiOpenMaterials}` (from the `academicons` package) to mark open-access status, open data, and open materials. When adding a new publication, add the corresponding entry to `francesco_bailo_cv.bib` first, then reference its key.
- A custom `boxH` tcolorbox environment (defined near the top of the file) is used for the highlighted summary box at the start of the "Academic positions" section.
- A custom `\subsubsection` command is defined via `\NewDocumentCommand` (since moderncv doesn't provide one natively) to keep formatting consistent with `\cventry`-style two-column layout.
- Entries within each section are ordered **reverse-chronologically** (most recent first) — follow this when inserting new positions, grants, or publications.
- BibLaTeX entry keys follow a `lastname_ShortTitle_year` (or `firstauthorTitleWordsYear`) convention; match the existing style when adding new `.bib` entries.

## Keeping the CV in sync with Zotero

Francesco's Zotero library is the **source of truth** for publications and
presentations, but only nine specific collections (under
`https://zotero.org/users/1127234/collections/HM5SIRSB`) hold material
curated for the CV — his library also contains a lot that isn't meant to
appear here. Each monitored collection maps to one CV section (Peer-
reviewed, Books, Book sections, Research report, News articles, Media
appearances, Presentation, Thesis, Preprint); the full key list lives in
`.claude/zotero-cv-sync.json`. Notably: **preprints are dropped from the CV
once the peer-reviewed version is published** — if in doubt about a match,
ask Francesco rather than guessing.

To pull new/changed/superseded items from those collections and diff them
against `francesco_bailo_cv.tex`/`.bib`, use the **`zotero-cv-sync` skill**
(`.claude/skills/zotero-cv-sync/SKILL.md`), which runs
`scripts/zotero_sync.py`. That script talks to the Zotero Web API directly
(requires a read-only key in the `ZOTERO_API_KEY` env var — see the skill
for setup) because the `mcp__zotero__*` tools only support whole-library
search, not scoping to a specific collection. The script only reads and
reports a diff (including preprint-vs-published fuzzy matching); it never
edits the CV files itself — follow the skill's steps to apply changes.

## Keeping the CV in sync with the personal website's grants folder

Francesco's personal website repo also tracks his grants as individual
Markdown files with YAML frontmatter, one file per grant, in
`/Users/francesco/Documents/GitHub/my-website/_grants`. The site isn't
published yet, so this folder is only reachable locally (not via a public
URL) — read it directly off disk. Each file's frontmatter has fields
`title`, `permalink`, `funder`, `scheme`, `amount`, `start-date`, `end-date`,
`collaborators`, `projects`, and `status` (e.g. `success`).

These map to the CV's **External grants** and **Internal grants**
`\subsection`s (in `francesco_bailo_cv.tex`, under Research), where each
grant is a `\cvline{<date>}{<emph scheme/name>. <amount>. Awarded by
<funder>. Investigators: ...}` entry. When asked to update or check the
CV's grants, cross-reference the two lists by date/funder/scheme — this
folder has no companion sync script (unlike Zotero), so compare and edit
manually rather than looking for a skill to run.
