"""The canned Johnny line catalogue.

These are the lines pre-rendered for the moments that repeat: greeting, idle,
dismissal, and the filler that covers a slow answer. Substantive answers do
not live here -- they are written live and spoken by `avatar.tts`.

Pure stdlib: it is only a catalogue, imported by the runtime and by
`scripts/pregen_lines.py`.

Written with the `johnny-persona` skill: cynical about institutions and never
about the listener, tech-noir imagery rather than bro slang, "choom" five times
across the whole set and never opening a line. The two idle lines marked below
are the owner's own wording.
"""
import hashlib
import random

MOMENTS = ("greeting", "idle", "dismissal", "filler")

LINES = {
    "greeting": (
        "Back from the dead. What's the damage today?",
        "Alright, I'm up. Let's see what the suits broke while I was out.",
        "Somebody said my name. Talk to me, choom.",
        "Awake. Not happy about it, but awake.",
        "Ghost in your machine, reporting in. Go on.",
        "You rang. What's the grid doing to you today?",
        "Still here. Still watching the tape.",
    ),
    "idle": (
        "So what are we doing today, choom?",          # owner's wording
        "Are we just idling then?",                     # owner's wording
        "You gonna ask me something, or are we just watching the numbers bleed?",
        "Market's moving whether you talk to me or not.",
        "Quiet. That's usually when the suits are up to something.",
        "I've got nowhere else to be. Neither do your positions, apparently.",
        "Say the word and I'll pull the tape.",
        "Still here, choom. Clock's running on somebody.",
    ),
    "dismissal": (
        "Yeah, yeah. I'll be in the wiring if you need me.",
        "Going dark. Don't sign anything while I'm out.",
        "Later, choom. Watch your exits.",
        "Fine. Wake me when it gets interesting.",
        "Gone. The grid keeps running without both of us.",
    ),
    "filler": (
        "Hang on. Pulling the numbers.",
        "Give me a second -- digging through the noise.",
        "Checking. Truth's buried under a lot of press releases.",
        "Working on it, choom.",
        "One sec. Reading what they'd rather you didn't.",
        "Let me look. Numbers don't spin as hard as the suits do.",
        "Hold on. Running it down.",
        "Yeah, let me see what the tape actually says.",
    ),
}


def slug(text: str) -> str:
    """Stable id for a line: manifest key, filename part, regeneration trigger.

    Deriving it from the text is what makes an edited line rebuild on its own.
    Bullion's equivalent cache keys on the output filename instead, so its
    docstring has to warn that editing a script means deleting the stale wav by
    hand.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def all_lines() -> list:
    """Every (moment, text) pair in catalogue order."""
    return [(moment, text) for moment in MOMENTS for text in LINES[moment]]


def pick(moment: str, exclude: str = None) -> str:
    """A line for `moment`, avoiding `exclude` so it does not repeat back to back.

    `exclude` is line text, not a slug -- callers never handle ids. When the
    moment holds only one line it is returned even if excluded: repeating
    beats saying nothing.
    """
    choices = LINES[moment]
    remaining = tuple(text for text in choices if text != exclude)
    return random.choice(remaining or choices)
