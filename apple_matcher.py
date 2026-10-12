"""Core: Serato crate -> most-likely Apple Music match per track.

Searches the iTunes Search API and disambiguates using the filename itself:
the candidate's artist tokens must appear in the filename, and the rest of
the filename must resemble the candidate's title. Tracks with no confident
match are reported as not available on Apple Music.
"""
import json
import os
import re
import struct
import urllib.parse
import urllib.request

VIDEO_JUNK = re.compile(
    r"\s*\((Official\s(Music\s)?Video|Official\sLyric\sVideo|Official\sAudio|Visualizer)\)",
    re.IGNORECASE)
VERSION_TAGS = re.compile(
    r"\s*\((Dirty|Clean|Explicit|Radio\sEdit)\)", re.IGNORECASE)
FT_CLAUSE = re.compile(
    r"\s*\((ft\.?|feat\.?|featuring)\b[^)]*\)|\s+(ft\.?|feat\.?|featuring)\s+.*$",
    re.IGNORECASE)

STOP = {"the", "a", "an", "ft", "feat", "featuring", "vs", "and", "with",
        "remix", "edit", "version", "original", "extended", "radio", "dirty",
        "clean", "explicit", "part", "pt", "mix"}


def first_content_token(s):
    for t in tokens(s):
        if len(t) > 2 and t not in STOP:
            return t
    return None


def search_query(artist, title):
    t = VERSION_TAGS.sub("", title)
    t = FT_CLAUSE.sub("", t)
    q = f"{artist} {t}".strip()
    return re.sub(r"\s+", " ", q)


def parse_crate(path):
    data = open(path, "rb").read()
    tracks = []

    def walk(buf):
        pos = 0
        while pos + 8 <= len(buf):
            tag = buf[pos:pos + 4]
            if not all(32 <= b < 127 for b in tag):
                break
            length = struct.unpack(">I", buf[pos + 4:pos + 8])[0]
            payload = buf[pos + 8:pos + 8 + length]
            tag_s = tag.decode("ascii")
            if tag_s == "ptrk":
                tracks.append(payload.decode("utf-16-be", errors="replace"))
            elif tag_s in ("otrk", "ovct", "osrt"):
                walk(payload)
            pos += 8 + length

    walk(data)
    return tracks


def clean_stem(filename):
    stem = os.path.splitext(os.path.basename(filename.replace("\\", "/")))[0]
    stem = re.sub(r"^\d+\s+", "", stem)
    stem = VIDEO_JUNK.sub("", stem)
    return re.sub(r"\s+", " ", stem).strip()


def tokens(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def itunes_search(query, limit=8):
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": query, "entity": "song", "limit": limit, "country": "US"})
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r).get("results", [])


def title_sim(a, b):
    """Similarity of two titles; remix/version of the same song scores high."""
    import difflib
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    base = difflib.SequenceMatcher(None, a, b).ratio()
    if b.startswith(a) or a.startswith(b):
        base = max(base, 0.85)
    return base


def _is_explicit(h):
    return h.get("trackExplicitness") == "explicit"


def _is_clean(h):
    return h.get("trackExplicitness") == "cleaned"


def _split_candidates(scored):
    """scored = [(score, hit), ...] sorted desc. Return (primary, clean_alt).

    Primary prefers the explicit version (DJ crates); clean_alt is the
    cleaned version when one exists, for radio gigs.
    """
    if not scored:
        return None, None
    scored.sort(key=lambda x: -x[0])
    best = scored[0][1]
    expl = next((h for _, h in scored if _is_explicit(h)), None)
    primary = expl or best
    primary_id = primary.get("trackId")
    clean = next((h for _, h in scored
                  if _is_clean(h) and h.get("trackId") != primary_id), None)
    return primary, clean


def _clean_fallback(artist, title, primary):
    """One extra search for the cleaned version, for radio gigs."""
    if not primary or not _is_explicit(primary):
        return None
    try:
        results = itunes_search(f"{artist} {title} clean")
    except Exception:
        return None
    anchor = first_content_token(title)
    ca_toks = set(tokens(artist))
    best, best_s = None, 0.0
    for h in results:
        if not _is_clean(h):
            continue
        if h.get("trackId") == primary.get("trackId"):
            continue
        cand_title = h.get("trackName", "")
        if anchor and anchor not in set(tokens(cand_title)):
            continue
        ha_toks = set(tokens(h.get("artistName", "")))
        if not ca_toks or not ha_toks:
            continue
        a_s = 2 * len(ca_toks & ha_toks) / (len(ca_toks) + len(ha_toks))
        t_s = title_sim(title, cand_title)
        s = 0.6 * a_s + 0.4 * t_s
        if s > best_s:
            best, best_s = h, s
    return best if best_s >= 0.45 else None


def match_dash_split(artist, title):
    """Filename had 'Artist - Title': verify against Apple Music strictly.

    Returns (primary, clean_alt, score): primary prefers the explicit
    version, clean_alt is the cleaned version for radio gigs.
    """
    anchor = first_content_token(title)
    cleaned = FT_CLAUSE.sub("", VERSION_TAGS.sub("", title))
    ca_toks = set(tokens(artist))
    for query in (search_query(artist, title),
                  f"{artist} {' '.join(tokens(cleaned)[:3])}"):
        try:
            results = itunes_search(query)
        except Exception:
            return None, None, 0.0
        scored = []
        for h in results:
            cand_title = h.get("trackName", "")
            if anchor and anchor not in set(tokens(cand_title)):
                continue  # different song that shares words
            ha_toks = set(tokens(h.get("artistName", "")))
            if not ca_toks or not ha_toks:
                continue
            a_s = 2 * len(ca_toks & ha_toks) / (len(ca_toks) + len(ha_toks))
            t_s = title_sim(title, cand_title)
            s = 0.6 * a_s + 0.4 * t_s
            if s >= 0.45:
                scored.append((s, h))
        if scored:
            primary, clean = _split_candidates(scored)
            p_s = next(s for s, h in scored
                       if h.get("trackId") == primary.get("trackId"))
            if not clean:
                clean = _clean_fallback(artist, title, primary)
            return primary, clean, p_s
    return None, None, 0.0


def match_whole_stem(stem):
    """No ' - ' in filename: search the whole stem, disambiguate.

    Returns (primary, clean_alt, score).
    """
    try:
        results = itunes_search(stem)
    except Exception:
        return None, None, 0.0
    s_toks = tokens(stem)
    s_set = set(s_toks)
    scored = []
    for h in results:
        a_toks = tokens(h.get("artistName", ""))
        if not a_toks:
            continue
        # candidate's artist tokens must (mostly) appear in the filename
        cov = sum(1 for t in a_toks if t in s_set) / len(a_toks)
        if cov < 0.5:
            continue
        # remainder of filename should resemble the track title
        a_set = set(a_toks)
        remainder = " ".join(t for t in s_toks if t not in a_set)
        anchor = first_content_token(remainder)
        if anchor and anchor not in set(tokens(h.get("trackName", ""))):
            continue  # different song that shares words
        t_s = title_sim(remainder, h.get("trackName", ""))
        s = 0.5 * cov + 0.5 * t_s
        if s >= 0.6:
            scored.append((s, h))
    if not scored:
        return None, None, 0.0
    primary, clean = _split_candidates(scored)
    p_s = next(s for s, h in scored
               if h.get("trackId") == primary.get("trackId"))
    if not clean and _is_explicit(primary):
        try:
            fb = itunes_search(stem + " clean")
        except Exception:
            fb = []
        anchor = first_content_token(stem)
        fb_scored = []
        for h in fb:
            if not _is_clean(h) or h.get("trackId") == primary.get("trackId"):
                continue
            a_toks = tokens(h.get("artistName", ""))
            if not a_toks:
                continue
            cov = sum(1 for t in a_toks if t in s_set) / len(a_toks)
            if cov < 0.5:
                continue
            if anchor and anchor not in set(tokens(h.get("trackName", ""))):
                continue
            fb_scored.append((0.6, h))
        if fb_scored:
            clean = fb_scored[0][1]
    return primary, clean, p_s


def _hit_info(h):
    if not h:
        return None
    return {"artist": h.get("artistName"), "title": h.get("trackName"),
            "url": h.get("trackViewUrl"),
            "explicit": _is_explicit(h)}


def find_link(filename):
    """Return (primary_or_None, clean_alt_or_None, score, display_label)."""
    stem = clean_stem(filename)
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        label = f"{artist.strip()} - {title.strip()}"
        primary, clean, score = match_dash_split(artist.strip(), title.strip())
    else:
        label = stem
        primary, clean, score = match_whole_stem(stem)
    return _hit_info(primary), _hit_info(clean), score, label


def crate_links(crate_path, progress_cb=None, delay=0.3):
    """Yield (label, primary_or_None, clean_alt_or_None, score) per track."""
    import time
    tracks = parse_crate(crate_path)
    for i, ptrk in enumerate(tracks):
        filename = ptrk.replace("\\", "/").split("/")[-1]
        if progress_cb:
            progress_cb(i + 1, len(tracks), filename)
        primary, clean, score, label = find_link(filename)
        yield label, primary, clean, score
        time.sleep(delay)
