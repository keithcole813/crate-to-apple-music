#!/usr/bin/env python3
"""
Serato crate -> Apple Music converter.

Takes a Serato .crate file, finds each track in Google Drive, downloads it,
converts to phone-friendly M4A (AAC 256k), tags it, and writes an M3U
playlist. Drag the output folder into Apple Music once (with Sync Library
on) and the whole crate lands on your phone.

Usage:
    python crate_to_apple_music.py "/path/to/My Crate.crate" -o ./output

Requires: hatch_gws_cli (Google Drive access), ffmpeg, python3-mutagen
"""
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys

DRY_RUN = False


def gws(*args):
    """Run hatch_gws_cli and return parsed JSON stdout."""
    cmd = ["hatch_gws_cli"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # not all commands emit JSON on failure; surface stderr
        raise RuntimeError(f"gws failed: {' '.join(args)}\n{r.stderr[:500]}")
    # some commands print a JSON status line plus other text; find the JSON
    out = r.stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # try to find a JSON object in the output
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise RuntimeError(f"could not parse gws output: {out[:300]}")


# ---------- .crate parsing ----------
def parse_crate(path):
    """Return list of track file paths referenced by a Serato .crate file."""
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


# ---------- Drive ----------
def drive_find(filename):
    """Find a file on Drive by exact name. Returns (id, size) or None."""
    # escape single quotes for the query
    q = filename.replace("'", "\\'")
    res = gws("drive", "files", "list", "--params",
              json.dumps({"q": f"name = '{q}' and trashed = false",
                          "fields": "files(id, name, size)"}))
    files = res.get("files", [])
    if not files:
        return None
    # prefer the largest (in case of dupes)
    files.sort(key=lambda f: int(f.get("size") or 0), reverse=True)
    return files[0]["id"], int(files[0].get("size") or 0)


def drive_download(file_id, dest):
    res = gws("drive", "files", "get", "--params",
              json.dumps({"fileId": file_id, "alt": "media"}),
              "-o", dest)
    return res.get("status") == "success"


# ---------- tagging ----------
def read_tags(path):
    """Return (artist, title) from audio tags, or (None, None)."""
    try:
        from mutagen import File as MutagenFile
        m = MutagenFile(path, easy=True)
        if not m:
            return None, None
        artist = (m.get("artist") or [None])[0]
        title = (m.get("title") or [None])[0]
        return artist, title
    except Exception:
        return None, None


def split_filename(name):
    """Fallback: parse 'NN Title Artist1,Artist2.ext' or 'Artist - Title.ext'."""
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r"^\d+\s+", "", stem)  # strip leading track number
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        # drop trailing parentheticals like (Official Video) from title for cleanliness,
        # but keep (Dirty)/(Remix) markers
        return artist.strip(), title.strip()
    # Pattern: "Title Artist1,Artist2" — artists are the comma-separated tail
    m = re.search(r"^(.*?)\s+([A-Z][\w\.\$&']*(?:\s*,\s*[A-Z][\w\.\$&']*)+)$", stem)
    if m:
        title, artists = m.group(1).strip(), m.group(2).strip()
        return artists.replace(",", ", "), title
    # last resort: "Title Artist" (single artist, no comma)
    parts = stem.rsplit(" ", 1)
    if len(parts) == 2 and len(parts[1]) > 1:
        return parts[1], parts[0]
    return "Unknown Artist", stem


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()


def clean_display(artist, title):
    """Tidy up messy DJ-pool tags: drop doubled artist, video junk."""
    # title already starts with the artist -> don't double it
    first_artist = artist.split(",")[0].strip().lower()
    if title.lower().startswith(first_artist):
        disp_title = title
        disp_artist = ""
    else:
        disp_title, disp_artist = title, artist
    # drop "(Official Video)"-style junk, keep (Dirty)/(Remix)/[feat. x]
    disp_title = re.sub(
        r"\s*\((Official\s(Music\s)?Video|Official\sLyric\sVideo)\)", "",
        disp_title, flags=re.IGNORECASE).strip()
    if disp_artist:
        return f"{safe_name(disp_artist)} - {safe_name(disp_title)}"
    return safe_name(disp_title)


def norm_key(artist, title):
    return re.sub(r"\W+", "", (artist + title).lower())


# ---------- conversion ----------
def convert_to_m4a(src, dest):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src,
         "-vn", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", dest],
        check=True)


def tag_m4a(path, artist, title):
    try:
        from mutagen.mp4 import MP4
        m = MP4(path)
        m["\xa9ART"] = [artist]
        m["\xa9nam"] = [title]
        m.save()
    except Exception as e:
        print(f"  (tag warning: {e})")


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Convert a Serato crate to Apple Music-ready files.")
    ap.add_argument("crate", help="Path to the .crate file")
    ap.add_argument("-o", "--out", default="./apple_music_out", help="Output folder")
    args = ap.parse_args()

    try:
        from mutagen import File as _  # noqa
    except ImportError:
        print("Installing mutagen…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "--break-system-packages", "mutagen"], check=True)

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH.")

    tracks = parse_crate(args.crate)
    print(f"Crate has {len(tracks)} tracks.\n")
    if not tracks:
        sys.exit("No tracks found in crate.")

    outdir = os.path.abspath(args.out)
    os.makedirs(outdir, exist_ok=True)
    tmpdir = os.path.join(outdir, "_tmp")
    os.makedirs(tmpdir, exist_ok=True)

    playlist = []
    missing = []
    seen_keys = set()
    done = 0

    for i, ptrk in enumerate(tracks, 1):
        filename = ptrk.replace("\\", "/").split("/")[-1]
        print(f"[{i}/{len(tracks)}] {filename}")
        try:
            found = drive_find(filename)
            if not found:
                print("  NOT FOUND on Drive")
                missing.append(filename)
                continue
            file_id, size = found
            print(f"  found on Drive ({size / 1048576:.1f} MB), downloading…")
            tmp_path = os.path.join(tmpdir, filename)
            if not os.path.exists(tmp_path):
                drive_download(file_id, tmp_path)

            artist, title = read_tags(tmp_path)
            if not artist or not title:
                artist, title = split_filename(filename)
            # skip true dupes (same track listed twice / tag vs filename variants)
            key = norm_key(artist, title)
            if key in seen_keys:
                print(f"  duplicate of an earlier track, skipping")
                continue
            seen_keys.add(key)
            out_name = clean_display(artist, title) + ".m4a"
            out_path = os.path.join(outdir, out_name)
            # avoid collisions
            n = 2
            base = out_name
            while os.path.exists(out_path):
                out_name = base[:-4] + f" ({n}).m4a"
                out_path = os.path.join(outdir, out_name)
                n += 1

            if filename.lower().endswith(".m4a"):
                shutil.copy(tmp_path, out_path)
            else:
                print(f"  converting to M4A…")
                convert_to_m4a(tmp_path, out_path)
            tag_m4a(out_path, artist, title)
            print(f"  -> {out_name}")
            playlist.append(out_name)
            done += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            missing.append(f"{filename} (error: {e})")

    # M3U playlist
    crate_name = os.path.splitext(os.path.basename(args.crate))[0]
    m3u_path = os.path.join(outdir, f"{safe_name(crate_name)}.m3u")
    with open(m3u_path, "w") as f:
        f.write("#EXTM3U\n")
        for p in playlist:
            f.write(p + "\n")

    # clean tmp
    shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\nDone: {done}/{len(tracks)} tracks -> {outdir}")
    print(f"Playlist: {m3u_path}")
    if missing:
        print(f"\nMissing from Drive ({len(missing)}):")
        for m in missing:
            print(f"  - {m}")
    print("\nNext: drag the .m4a files into Apple Music (Music app on Mac,\n"
          "or iTunes/Apple Music on Windows). With Sync Library on,\n"
          "they'll appear on your iPhone for workouts.")


if __name__ == "__main__":
    main()
