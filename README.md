# crate-to-apple-music

Two ways to get a Serato crate into Apple Music.

## 1. Streaming links (new)

`crate_to_apple_links.py` — cross-checks every song in a `.crate` against
Apple Music and links the most likely match for streaming:

```
python crate_to_apple_links.py "My Crate.crate" -o links.html
```

Songs that aren't on Apple Music get a clear "⚠️ Not on Apple Music" note
instead of a bad guess. Output is a tap-friendly HTML page.

**Web version** (`web_app.py`, runs port 5003): upload a `.crate` from your
phone, get the links page back. Same matching, no terminal needed.

## 2. Phone-ready files (for DJ-pool/underground cuts)

`crate_to_apple_music.py` — for tracks that aren't streaming anywhere:

```
python crate_to_apple_music.py "My Crate.crate" -o ./MyCrate
```

Finds each track in Google Drive, downloads, converts to M4A (AAC 256k),
tags it, writes an `.m3u`. Drag the files into Apple Music once — with
Sync Library on, the crate lands on your iPhone.

## Requirements

- Python 3 (no extra packages for the links script — stdlib only)
- Web version: `pip install flask`
- File converter: `mutagen`, `ffmpeg`, and Google Drive access via
  `hatch_gws_cli` (runs in Muse's environment — just ask and I'll
  convert a crate for you)
