#!/usr/bin/env python3
"""
Fetch the monitored Zotero collections (source of truth) and diff them
against francesco_bailo_cv.tex / francesco_bailo_cv.bib.

This script only reads from Zotero and reads the local CV files. It never
writes anything — it prints a structured JSON report to stdout describing
what's new, changed, or superseded, for a human (or Claude) to fold into
the CV by hand.

Auth: requires a read-only Zotero API key in the ZOTERO_API_KEY env var.
Create one at https://www.zotero.org/settings/keys (grant read access to
your library; no write access needed).

Usage:
    ZOTERO_API_KEY=... python3 scripts/zotero_sync.py
"""
import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.request
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEX_FILE = REPO_ROOT / "francesco_bailo_cv.tex"
BIB_FILE = REPO_ROOT / "francesco_bailo_cv.bib"
CONFIG_FILE = REPO_ROOT / ".claude" / "zotero-cv-sync.json"

DEFAULT_USER_ID = "1127234"
API_BASE = "https://api.zotero.org"

# The collections to monitor, and which part of the CV each one drives.
# "Presentation" is handled separately (it maps to \cventry blocks, not
# \fullcite/.bib entries). Everything else is bib-backed. Overridable via
# .claude/zotero-cv-sync.json ("collections" key).
DEFAULT_MONITORED_COLLECTIONS = [
    {"key": "D875BVLH", "section": "Peer-reviewed"},
    {"key": "ZS3JA2MY", "section": "Books"},
    {"key": "7RZXY9NH", "section": "Book sections"},
    {"key": "ERVQDLKJ", "section": "Research report"},
    {"key": "G3JSTCMW", "section": "News articles"},
    {"key": "WV9BRA2D", "section": "Media appearances"},
    {"key": "FLNATXSL", "section": "Presentation"},
    {"key": "75Y5AZ9G", "section": "Thesis"},
    {"key": "ZZ27UTBI", "section": "Preprint"},
]

# Sanity-check only: flags items whose itemType looks inconsistent with
# the collection they were filed under (e.g. a journalArticle accidentally
# left in the Preprint collection). Doesn't block anything.
EXPECTED_ITEM_TYPES = {
    "Peer-reviewed": {"journalArticle", "conferencePaper"},
    "Books": {"book"},
    "Book sections": {"bookSection"},
    "Research report": {"report"},
    "News articles": {"webpage", "blogPost", "newspaperArticle", "magazineArticle"},
    "Media appearances": {"webpage", "blogPost", "newspaperArticle", "magazineArticle",
                           "podcast", "radioBroadcast", "tvBroadcast", "interview", "document"},
    "Presentation": {"presentation"},
    "Thesis": {"thesis"},
    "Preprint": {"preprint", "manuscript"},
}

# entrytypes in the .bib that plausibly represent an unpublished preprint
# rather than a finished, citable publication.
PREPRINT_LIKE_BIB_ENTRYTYPES = {"unpublished", "online", "misc"}

# Fuzzy-match threshold (0-1, difflib SequenceMatcher ratio on normalized
# titles) above which a preprint is considered "likely superseded" by a
# published version. This is advisory only — always confirm with the user
# before dropping anything, per their explicit instruction.
SUPERSESSION_THRESHOLD = 0.6

SKIP_ITEM_TYPES = {"attachment", "note"}


def api_get(path, params=None):
    api_key = os.environ["ZOTERO_API_KEY"]
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Zotero-API-Version": "3",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.headers


def api_get_paginated(path, params=None):
    params = dict(params or {})
    params.setdefault("limit", 100)
    start = 0
    items = []
    while True:
        params["start"] = start
        batch, _headers = api_get(path, params)
        items.extend(batch)
        if len(batch) < params["limit"]:
            break
        start += params["limit"]
    return items


def fetch_collection_items_recursive(user_id, root_key):
    """Items in root_key plus all of its nested subcollections, deduped by item key."""
    keys = [root_key]

    def recurse(key):
        for child in api_get_paginated(f"/users/{user_id}/collections/{key}/collections"):
            keys.append(child["key"])
            recurse(child["key"])

    recurse(root_key)

    items = []
    seen = set()
    for k in keys:
        for it in api_get_paginated(f"/users/{user_id}/collections/{k}/items/top"):
            if it["key"] not in seen:
                seen.add(it["key"])
                items.append(it)
    return items


def load_monitored_collections():
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        return cfg.get("collections", DEFAULT_MONITORED_COLLECTIONS)
    return DEFAULT_MONITORED_COLLECTIONS


def load_user_id():
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
        if cfg.get("user_id"):
            return cfg["user_id"]
    return os.environ.get("ZOTERO_USER_ID", DEFAULT_USER_ID)


def extract_extra_citekey(extra):
    if not extra:
        return None
    for line in extra.splitlines():
        m = re.match(r"\s*Citation Key:\s*(\S+)", line)
        if m:
            return m.group(1)
    return None


def creator_names(creators, creator_type=None):
    out = []
    for c in creators or []:
        if creator_type and c.get("creatorType") != creator_type:
            continue
        if "name" in c:
            out.append(c["name"])
        else:
            out.append(f"{c.get('firstName','').strip()} {c.get('lastName','').strip()}".strip())
    return out


# LaTeX accent-command diacritic -> Unicode combining mark, so decode_latex_accents
# can turn e.g. \`a or \`{a} into 'à' (matching how Zotero stores it natively).
LATEX_ACCENT_TO_COMBINING = {
    "`": "\u0300",   # grave        \`a  -> à
    "'": "\u0301",   # acute        \'e  -> é
    '"': "\u0308",   # diaeresis    \"u  -> ü
    "^": "\u0302",   # circumflex   \^o  -> ô
    "~": "\u0303",   # tilde        \~n  -> ñ
    "c": "\u0327",   # cedilla      \c{c} -> ç
}


def decode_latex_accents(text):
    """Turn LaTeX accent macros (\\`a, \\'{e}, ...) into precomposed Unicode
    (à, é, ...), matching how Zotero exports the same characters natively.
    Without this, comparing a Zotero title to a BibLaTeX-exported title with
    accents diverges silently (e.g. 'società' vs 'societ`a').
    """
    if not text:
        return text

    def repl(m):
        mark, letter = m.group(1), m.group(2)
        combining = LATEX_ACCENT_TO_COMBINING.get(mark)
        if not combining:
            return m.group(0)
        return unicodedata.normalize("NFC", letter + combining)

    text = re.sub(r"\\([`'\"^~c])\{([a-zA-Z])\}", repl, text)
    text = re.sub(r"\\([`'\"^~c])([a-zA-Z])", repl, text)
    return text


def normalize_title(title):
    """Lowercase, strip accents (NFKD-decompose + drop combining marks), and
    collapse everything else to single spaces. Accent-stripping (rather than
    just discarding non-ASCII chars) is what lets an accented Zotero title
    match its BibLaTeX-decoded counterpart from decode_latex_accents().
    """
    text = unicodedata.normalize("NFKD", (title or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def title_similarity(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def load_existing_bib_entries():
    """Parse francesco_bailo_cv.bib into a list of {key, entrytype, title, title_norm, doi}."""
    text = BIB_FILE.read_text()
    entries = []
    starts = list(re.finditer(r"@(\w+)\{([^,\n]+),", text))
    for i, m in enumerate(starts):
        entrytype = m.group(1).lower()
        key = m.group(2).strip()
        chunk_start = m.end()
        chunk_end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        chunk = text[chunk_start:chunk_end]
        # (?<![a-zA-Z]) so 'title' doesn't also match the tail of
        # 'shorttitle'/'booktitle'. Brace-depth-aware extraction (not a
        # lazy regex up to the next '},') because titles routinely contain
        # commas after a nested brace group, e.g. '{...{{AI}}, Fake News...}'
        # — a '\}+,'-terminated regex truncates at that inner comma.
        title = ""
        title_field_m = re.search(r"(?<![a-zA-Z])title\s*=\s*", chunk)
        if title_field_m and title_field_m.end() < len(chunk) and chunk[title_field_m.end()] == "{":
            raw, _ = _first_brace_group(chunk, title_field_m.end())
            decoded = decode_latex_accents(raw or "")
            title = re.sub(r"[{}\\]", "", decoded).strip()
        doi_m = re.search(r"doi\s*=\s*\{([^}]+)\}", chunk, re.I)
        doi = doi_m.group(1).lower() if doi_m else None
        entries.append({
            "key": key, "entrytype": entrytype, "title": title,
            "title_norm": normalize_title(title), "doi": doi,
        })
    return entries


def load_cited_bib_keys():
    """Bib keys actually referenced via \\fullcite{...} anywhere in the .tex file."""
    return set(re.findall(r"\\fullcite\{([^}]+)\}", TEX_FILE.read_text()))


def _first_brace_group(text, pos):
    """Given text and an index pointing at '{', return (content, index_after_closing_brace).

    Handles nested braces by depth counting. Returns (None, pos) if text[pos] != '{'.
    """
    if pos >= len(text) or text[pos] != "{":
        return None, pos
    depth = 0
    start = pos
    i = pos
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], len(text)


def load_existing_presentations():
    """Return (set of date strings, normalized full-block text) for the Presentations section.

    Dates are extracted with a brace-depth-aware scan (robust to the file's
    mix of single-line/multi-line \\cventry and trailing '% comment' forms).
    Title matching is done as substring containment against the normalized
    block text rather than trying to regex out each title precisely, since
    titles appear in varied wrapping (`...'`, \\href{...}{...}, etc).
    """
    text = TEX_FILE.read_text()
    start = text.index(r"\subsection{\hspace{-2.5cm}Presentations}")
    end = text.index(r"\subsection{\hspace{-2.5cm}Media appearances}")
    block = text[start:end]

    dates = set()
    for m in re.finditer(r"\\cventry\b", block):
        i = m.end()
        eol = block.find("\n", i)
        i = eol + 1 if eol != -1 else len(block)
        while i < len(block):
            if block[i] in " \t\r\n":
                i += 1
                continue
            if block[i] == "%":
                nl = block.find("\n", i)
                i = nl + 1 if nl != -1 else len(block)
                continue
            break
        date, _ = _first_brace_group(block, i)
        if date is not None:
            dates.add(date.strip())

    return dates, normalize_title(block)


def fetch_biblatex(user_id, item_keys):
    if not item_keys:
        return ""
    api_key = os.environ["ZOTERO_API_KEY"]
    url = (f"{API_BASE}/users/{user_id}/items?itemKey={','.join(item_keys)}"
           f"&format=biblatex&limit=100")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "Zotero-API-Version": "3",
    })
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8")


def find_preprint_supersession(preprint_items, peer_reviewed_items, existing_bib_entries):
    """For each Preprint-collection item, find the best-matching published title
    (from the live Peer-reviewed collection, or from already-published .bib
    entries) and flag it as likely superseded above SUPERSESSION_THRESHOLD.
    """
    candidates = []
    for it in peer_reviewed_items:
        t = normalize_title(it["data"].get("title", ""))
        if t:
            candidates.append((t, f"Zotero Peer-reviewed collection: \"{it['data'].get('title')}\""))
    for e in existing_bib_entries:
        if e["entrytype"] in {"article", "inproceedings"} and e["title_norm"]:
            candidates.append((e["title_norm"], f"existing .bib entry '{e['key']}' ({e['entrytype']})"))

    results = []
    for pit in preprint_items:
        pdata = pit["data"]
        ptitle_norm = normalize_title(pdata.get("title", ""))
        best_score, best_label = 0.0, None
        for cand_norm, label in candidates:
            score = title_similarity(ptitle_norm, cand_norm)
            if score > best_score:
                best_score, best_label = score, label
        results.append({
            "key": pit["key"],
            "title": pdata.get("title"),
            "date": pdata.get("date"),
            "best_match_score": round(best_score, 2),
            "likely_superseded": best_score >= SUPERSESSION_THRESHOLD,
            "matched_against": best_label,
        })
    return results


def find_stale_preprint_bib_entries(existing_bib_entries, peer_reviewed_items, cited_keys):
    """Existing .bib entries that (a) are actually cited in the CV, (b) look like
    an unpublished/preprint entrytype, and (c) title-match a now-published
    Peer-reviewed-collection item — i.e. the CV is still citing the preprint
    after the real thing came out.
    """
    published = [(normalize_title(it["data"].get("title", "")), it["data"].get("title"))
                 for it in peer_reviewed_items]

    results = []
    for e in existing_bib_entries:
        if e["entrytype"] not in PREPRINT_LIKE_BIB_ENTRYTYPES or e["key"] not in cited_keys:
            continue
        best_score, best_title = 0.0, None
        for norm, title in published:
            score = title_similarity(e["title_norm"], norm)
            if score > best_score:
                best_score, best_title = score, title
        if best_score >= SUPERSESSION_THRESHOLD:
            results.append({
                "bib_key": e["key"],
                "bib_title": e["title"],
                "matched_published_title": best_title,
                "score": round(best_score, 2),
            })
    return results


def main():
    if "ZOTERO_API_KEY" not in os.environ:
        print("ERROR: set ZOTERO_API_KEY (create a read-only key at "
              "https://www.zotero.org/settings/keys)", file=sys.stderr)
        sys.exit(1)

    user_id = load_user_id()
    monitored = load_monitored_collections()

    by_section = {}
    collections_report = []
    type_mismatch_items = []
    for mc in monitored:
        section = mc["section"]
        items = fetch_collection_items_recursive(user_id, mc["key"])
        real_items = [it for it in items if it["data"]["itemType"] not in SKIP_ITEM_TYPES]
        by_section[section] = real_items
        collections_report.append({"key": mc["key"], "section": section, "item_count": len(real_items)})

        expected = EXPECTED_ITEM_TYPES.get(section, set())
        if expected:
            for it in real_items:
                if it["data"]["itemType"] not in expected:
                    type_mismatch_items.append({
                        "key": it["key"], "title": it["data"].get("title"),
                        "itemType": it["data"]["itemType"], "collection_section": section,
                        "expected_types": sorted(expected),
                    })

    existing_bib_entries = load_existing_bib_entries()
    existing_dois = {e["doi"] for e in existing_bib_entries if e["doi"]}
    existing_titles = {e["title_norm"] for e in existing_bib_entries if e["title_norm"]}
    cited_keys = load_cited_bib_keys()
    existing_pres_dates, existing_pres_block_norm = load_existing_presentations()

    preprint_items = by_section.get("Preprint", [])
    peer_reviewed_items = by_section.get("Peer-reviewed", [])
    presentation_items = by_section.get("Presentation", [])

    preprint_status = find_preprint_supersession(preprint_items, peer_reviewed_items, existing_bib_entries)
    superseded_preprint_keys = {r["key"] for r in preprint_status if r["likely_superseded"]}
    stale_preprint_bib_entries = find_stale_preprint_bib_entries(
        existing_bib_entries, peer_reviewed_items, cited_keys)

    new_bib_items = []
    seen = set()
    for section, items in by_section.items():
        if section == "Presentation":
            continue
        for it in items:
            if it["key"] in seen:
                continue
            if section == "Preprint" and it["key"] in superseded_preprint_keys:
                # Per user's rule: a preprint is dropped once the real paper is
                # published, so don't propose adding it as new.
                continue
            data = it["data"]
            doi = (data.get("DOI") or "").lower()
            title_norm = normalize_title(data.get("title", ""))
            already_present = (doi and doi in existing_dois) or (title_norm in existing_titles)
            if already_present:
                continue
            seen.add(it["key"])
            new_bib_items.append({
                "key": it["key"],
                "itemType": data["itemType"],
                "title": data.get("title"),
                "date": data.get("date"),
                "doi": data.get("DOI"),
                "url": data.get("url"),
                "authors": creator_names(data.get("creators"), "author"),
                "citekey_hint": extract_extra_citekey(data.get("extra")),
                "target_cv_subsection": section,
            })

    new_presentations = []
    for it in presentation_items:
        data = it["data"]
        title_norm = normalize_title(data.get("title", ""))
        already_present = (data.get("date", "") in existing_pres_dates) or (
            bool(title_norm) and title_norm in existing_pres_block_norm)
        if not already_present:
            new_presentations.append({
                "key": it["key"],
                "title": data.get("title"),
                "date": data.get("date"),
                "meeting_name": data.get("meetingName") or None,
                "place": data.get("place") or None,
                "presenters": creator_names(data.get("creators"), "presenter"),
                "contributors": creator_names(data.get("creators"), "contributor"),
                "url": data.get("url"),
                "needs_venue_info": not (data.get("meetingName") and data.get("place")),
            })

    biblatex_text = fetch_biblatex(user_id, [it["key"] for it in new_bib_items])

    report = {
        "collections": collections_report,
        "type_mismatch_items": type_mismatch_items,
        "new_bib_items": new_bib_items,
        "new_bib_items_biblatex": biblatex_text,
        "new_presentations": new_presentations,
        "preprint_status": preprint_status,
        "stale_preprint_bib_entries_to_review": stale_preprint_bib_entries,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
