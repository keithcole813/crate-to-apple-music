# crate-to-apple-music

Converts a Serato `.crate` into phone-ready M4A files for Apple Music.
Built for the recreational side: take a DJ crate, get it on your iPhone
for workouts and listening away from the decks.

## What it does

1. Parses the `.crate` file (Serato binary format) → track list
2. Finds each track in Google Drive by filename
3. Downloads and converts to M4A (AAC 256k, phone-friendly)
4. Tags each file (artist/title) and writes an `.m3u` playlist
5. Skips duplicates, reports anything missing from Drive

## Usage

```
python crate_to_apple_music.py "My Crate.crate" -o ./MyCrate
```

Then drag the `.m4a` files into Apple Music (Music app on Mac, or
iTunes/Apple Music on Windows). With Sync Library turned on, the whole
crate appears on your iPhone.

## Requirements

- Python 3, `mutagen`, `ffmpeg` on PATH
- Google Drive access via `hatch_gws_cli` (runs in Muse's environment —
  just ask and I'll convert a crate for you)
