"""Resolves a moment to a pre-generated Johnny wav.

Everything here degrades rather than raises. The audio is a gitignored build
artifact of `scripts/pregen_lines.py`, so a fresh clone has none of it and an
interrupted run has some of it -- neither may stop the avatar from appearing. A moment with no usable audio simply passes over in silence, and
`missing` names what is absent so the caller can say so on screen.

An entry is only usable when its recorded hash still matches the catalogue's
text for that line. Audio built from an older wording says something the
catalogue no longer claims, which is worse than saying nothing.
"""
import json
from pathlib import Path

from avatar import lines

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "voice"
MANIFEST_NAME = "manifest.json"


def asset_dir(voice_name: str) -> Path:
    """Where the canned lines rendered in `voice_name` live.

    One directory per voice, so the greeting and the live answer are the same
    voice. `assets/voice` itself still holds the set cloned with ChatterboxTTS
    before 2026-10-01; nothing reads it now and nothing overwrites it.
    """
    return ASSET_DIR.with_name(f"voice-{voice_name}")


class CannedVoice:
    def __init__(self, root: Path = ASSET_DIR):
        self.root = Path(root)
        self.by_moment = {}
        self.missing = []
        self._load()

    @property
    def available(self) -> bool:
        return any(self.by_moment.values())

    def _load(self) -> None:
        wanted = {text: moment for moment, text in lines.all_lines()}
        usable = {}

        manifest = self.root / MANIFEST_NAME
        try:
            data = json.loads(manifest.read_text())
            entries = data["entries"]
        except (OSError, ValueError, KeyError, TypeError):
            self.missing = list(wanted)
            return

        for entry in entries:
            text = entry.get("text")
            moment = wanted.get(text)
            if moment is None or entry.get("hash") != lines.slug(text):
                continue
            path = self.root / entry.get("file", "")
            if not path.exists():
                continue
            usable.setdefault(moment, []).append((text, str(path)))

        self.by_moment = usable
        playable = {text for pairs in usable.values() for text, _ in pairs}
        self.missing = [text for text in wanted if text not in playable]

    def path_for(self, moment: str, exclude: str = None):
        """`(line_text, wav_path)` for `moment`, or None if nothing is playable.

        `exclude` is line text, matching `lines.pick`, so callers never handle
        slugs.
        """
        pairs = self.by_moment.get(moment)
        if not pairs:
            return None
        remaining = [pair for pair in pairs if pair[0] != exclude] or pairs
        texts = [text for text, _ in remaining]
        chosen = lines.random.choice(texts)
        return next(pair for pair in remaining if pair[0] == chosen)
