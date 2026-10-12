#!/usr/bin/env python3
"""CLI: Serato crate -> Apple Music links (most-likely match per track)."""
import argparse
import html
import os

from apple_matcher import crate_links

HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{crate} — Apple Music links</title>
<style>
body {{ background:#111; color:#eee; font-family:-apple-system,sans-serif;
       max-width:640px; margin:0 auto; padding:20px; }}
h1 {{ color:#f5c518; font-size:1.3em; }}
.song {{ display:block; background:#1c1c1e; border-radius:10px;
         padding:12px 14px; margin:8px 0; color:#fff; text-decoration:none; }}
.song small {{ color:#999; display:block; margin-top:2px; }}
.miss {{ background:#2a1a1a; color:#c99; padding:12px 14px; border-radius:10px; margin:8px 0; }}
</style></head><body>
<h1>{crate} — Apple Music</h1>
<p>{found} of {total} found for streaming.</p>
{items}
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Serato crate -> Apple Music links")
    ap.add_argument("crate", help="Path to the .crate file")
    ap.add_argument("-o", "--out", default=None, help="HTML output path")
    args = ap.parse_args()

    crate_name = os.path.splitext(os.path.basename(args.crate))[0]
    items, found, total = [], 0, 0

    def prog(i, n, name):
        print(f"[{i}/{n}] {name[:60]}")

    for label, match, score in crate_links(args.crate, progress_cb=prog):
        total += 1
        if match:
            found += 1
            url = match["trackViewUrl"]
            print(f"  -> {match['artistName']} - {match['trackName']} ({score:.2f})")
            items.append(
                f'<a class="song" href="{html.escape(url)}">'
                f"{html.escape(match['artistName'])} — {html.escape(match['trackName'])}"
                f"<small>for: {html.escape(label)}</small></a>")
        else:
            print(f"  NOTE: not available on Apple Music ({score:.2f})")
            items.append(
                f'<div class="miss">⚠️ Not on Apple Music: {html.escape(label)}</div>')

    out = args.out or os.path.splitext(args.crate)[0] + "_apple_music.html"
    with open(out, "w") as f:
        f.write(HTML_TEMPLATE.format(
            crate=html.escape(crate_name), found=found,
            total=total, items="\n".join(items)))
    print(f"\n{found}/{total} matched -> {out}")


if __name__ == "__main__":
    main()
