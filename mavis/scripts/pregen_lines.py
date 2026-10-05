"""Pre-render the canned Johnny lines in the voice he answers in.

Until 2026-10-01 this cloned each line with ChatterboxTTS under a separate
Python 3.12 + torch venv, at 35-41x realtime: 47 minutes for the set. The
lines are now rendered by the same `avatar.tts` voice that speaks his live
answers, under the ordinary runtime venv, in under a minute.

Each voice gets its own directory (`assets/voice-<name>/`), so switching
`MAVIS_TTS` never plays a greeting in one voice and an answer in another.
The old cloned set in `assets/voice/` is left alone.

Work is skipped when the manifest already holds an entry whose hash matches
the line's current text, whose voice setting matches, and whose wav exists.
The hash is of the text itself, so editing a line rebuilds exactly that line.

Usage, from mavis/:
    .venv/bin/python scripts/pregen_lines.py [--only MOMENT] [--dry-run]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from avatar import canned, lines, tts  # noqa: E402


def load_manifest(manifest):
    try:
        return json.loads(manifest.read_text())["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def save_manifest(manifest, entries):
    # Write to a sibling temp file and rename over the target rather than
    # writing the manifest in place: a kill between truncate and write would
    # otherwise leave partial JSON that load_manifest swallows as [],
    # orphaning every wav on disk and forcing a full regenerate.
    tmp = manifest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": 2, "entries": entries}, indent=2))
    os.replace(tmp, manifest)


def duration(path):
    try:
        from scipy.io import wavfile
        rate, data = wavfile.read(str(path))
        return round(len(data) / rate, 2)
    except (OSError, ValueError):
        return None


def voice_setting(voice) -> str:
    """What makes two renders of a line differ: the voice and its settings."""
    return "|".join(str(part) for part in (
        voice.name, getattr(voice, "voice_spec", ""), getattr(voice, "speed", ""),
        getattr(voice, "voice_id", "")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=lines.MOMENTS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    voice = tts.make_voice(strict=True)
    setting = voice_setting(voice)
    out_dir = canned.asset_dir(voice.name)
    manifest = out_dir / canned.MANIFEST_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    wanted = [(moment, text) for moment, text in lines.all_lines()
              if args.only is None or moment == args.only]

    catalogue = {lines.slug(text): text for _moment, text in lines.all_lines()}
    # Keep every entry that still matches the catalogue and still has its wav,
    # including moments outside a --only filter. Building `keep` from the
    # filtered list instead would rewrite the manifest without them.
    keep = [entry for entry in load_manifest(manifest)
            if catalogue.get(entry.get("hash")) == entry.get("text")
            and entry.get("voice") == setting
            and (out_dir / entry.get("file", "")).exists()]
    already = {entry["hash"] for entry in keep}

    todo = [(moment, text, lines.slug(text)) for moment, text in wanted
            if lines.slug(text) not in already]

    print(f"voice {setting}: {len(keep)} already rendered, {len(todo)} to generate")
    for moment, text, digest in todo:
        print(f"  [{moment}] {text}")
    if args.dry_run or not todo:
        return

    voice.start()       # a voice that cannot load fails here, loudly
    for index, (moment, text, digest) in enumerate(todo, 1):
        target = out_dir / f"{moment}-{digest}.wav"
        began = time.monotonic()
        voice.synth(text, str(target))
        seconds = duration(target)
        keep.append({"moment": moment, "text": text, "hash": digest,
                     "file": target.name, "seconds": seconds, "voice": setting})
        save_manifest(manifest, keep)   # after each line, so an interrupt keeps progress
        print(f"[{index}/{len(todo)}] {moment}: {seconds}s audio "
              f"in {time.monotonic() - began:.1f}s -- {text}")

    print(f"done: {len(keep)} lines in {out_dir}")


if __name__ == "__main__":
    main()
