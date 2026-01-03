from __future__ import annotations

import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# -----------------------------
# Hangman frames (EMPTY -> FULL)
# -----------------------------
FIGURES: list[str] = list(reversed([
    r"""
-+---+-
 |/  O
 |  /|\
 |  / \
 |
/|\
##########
""",
    r"""
-+---+-
 |/  O
 |  /|\
 |  /
 |
/|\
##########
""",
    r"""
-+---+-
 |/  O
 |  /|\
 |
 |
/|\
##########
""",
    r"""
-+---+-
 |/  O
 |  /|
 |
 |
/|\
##########
""",
    r"""
-+---+-
 |/  O
 |   |
 |
 |
/|\
##########
""",
    r"""
-+---+-
 |/  O
 |
 |
 |
/|\
##########
""",
    r"""
-+-----
 |/
 |
 |
 |
/|\
##########
""",
    r"""
-+-----
 |
 |
 |
 |
/|\
##########
""",
    r"""
 |
 |
 |
 |
 |
/|\
##########
""",
    r"""
 |
 |
 |
 |
 |
/|
##########
""",
    r"""
 |
 |
 |
 |
 |
 |
##########
""",
    """
\n\n\n\n\n
##########""",
]))


# -----------------------------
# Terminal rendering
# -----------------------------
class Terminal:
    def __init__(self, frames: Sequence[str]) -> None:
        self.frames = [f.rstrip("\n") for f in frames]
        self.h = max(len(f.splitlines()) for f in self.frames) if self.frames else 0
        self._first_draw = True

    def _pad(self, frame: str) -> str:
        lines = frame.splitlines()
        return "\n".join(lines + [""] * (self.h - len(lines))) + "\n"

    def draw(self, idx: int) -> None:
        idx = max(0, min(idx, len(self.frames) - 1))
        if not self._first_draw and self.h:
            sys.stdout.write(f"\x1b[{self.h}F")  # cursor up
        self._first_draw = False
        sys.stdout.write("\x1b[J")  # clear to end of screen
        sys.stdout.write(self._pad(self.frames[idx]))
        sys.stdout.flush()


# -----------------------------
# German normalization
# ä/ö/ü -> ae/oe/ue, ß -> ss
# also accept "sz" as guess alias for ß
# -----------------------------
def normalize_word_de(s: str) -> str:
    # casefold handles German casing more robustly than lower()
    s = s.casefold()
    out: list[str] = []
    for ch in s:
        if ch == "ä":
            out.append("ae")
        elif ch == "ö":
            out.append("oe")
        elif ch == "ü":
            out.append("ue")
        elif ch == "ß":
            out.append("ss")
        else:
            out.append(ch)
    return "".join(out)


def load_words(path: Path | None) -> list[str]:
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(f"Wortliste nicht gefunden: {path}")

    words: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        w = line.strip()
        if not w or any(c.isspace() for c in w):
            continue
        words.append(w)
    return words


def pick_word(words: Sequence[str]) -> str:
    if not words:
        words = [
            "Überraschung",
            "Straßenbahn",
            "Wörterbuch",
            "Programmieren",
            "KünstlicheIntelligenz",
            "größer",
        ]
    return random.choice(words)


# -----------------------------
# Game model
# -----------------------------
@dataclass
class HangmanGame:
    original_word: str
    max_wrong: int

    # state
    guessed: set[str] = field(default_factory=set)
    wrong: set[str] = field(default_factory=set)

    # derived
    word: str = field(init=False)          # normalized playable word (ae/oe/ue/ss)
    has_eszett: bool = field(init=False)

    def __post_init__(self) -> None:
        if self.max_wrong < 1:
            raise ValueError("max_wrong muss >= 1 sein")
        self.has_eszett = "ß" in self.original_word.casefold()
        self.word = normalize_word_de(self.original_word)

    @property
    def wrong_count(self) -> int:
        return len(self.wrong)

    @property
    def is_won(self) -> bool:
        needed = {c for c in self.word if c.isalpha()}
        return needed.issubset(self.guessed)

    @property
    def is_lost(self) -> bool:
        return self.wrong_count >= self.max_wrong

    def masked_word(self) -> str:
        out: list[str] = []
        for c in self.word:
            if c.isalpha():
                out.append(c if c in self.guessed else "_")
            else:
                out.append(c)
        return " ".join(out)

    def _apply_guess_letters(self, letters: Sequence[str]) -> bool:
        """Returns True if at least one new guess was applied."""
        changed = False
        for ch in letters:
            if ch in self.guessed or ch in self.wrong:
                continue
            if ch in {c for c in self.word if c.isalpha()}:
                self.guessed.add(ch)
                changed = True
            else:
                self.wrong.add(ch)
                changed = True
        return changed

    def guess(self, raw: str) -> tuple[bool, str]:
        raw = raw.strip()
        if not raw:
            return False, "Bitte eingeben 🙂"

        g = raw.casefold()

        # full word guess (optional, but nice)
        if len(g) > 2 and g.isalpha():
            if normalize_word_de(g) == self.word:
                self.guessed.update({c for c in self.word if c.isalpha()})
                return True, "Wort erraten ✅"
            self.wrong.add(g)  # track it, counts as one wrong attempt (string ok)
            return True, "Nope ❌"

        # special aliases for umlauts/ß
        # You can input: ä/ae, ö/oe, ü/ue, ß/ss/sz
        if g in {"ä", "ae"}:
            letters = ["a", "e"]
        elif g in {"ö", "oe"}:
            letters = ["o", "e"]
        elif g in {"ü", "ue"}:
            letters = ["u", "e"]
        elif g in {"ß", "ss", "sz"}:
            letters = ["s"]  # word contains "ss" after normalization, so 's' is enough
        elif g == "z" and self.has_eszett:
            # allow "sz" idea: if original had ß, accept z as alias to help the player
            letters = ["s"]
        else:
            # regular single-letter guess
            g = g[0]
            if not g.isalpha():
                return False, "Nur Buchstaben bitte 🙂"
            letters = [g]

        # prevent "double guess" noise
        if all((ch in self.guessed or ch in self.wrong) for ch in letters):
            return False, f"'{raw}' hattest du schon."

        # apply: for multi-letter (ae/oe/ue) we reveal both letters in one move
        # but wrong attempts should count as ONE move, not per letter
        # => if at least one letter hits, ok; otherwise mark a single wrong token
        target_letters = {c for c in self.word if c.isalpha()}
        hit = any(ch in target_letters for ch in letters)

        if hit:
            for ch in letters:
                if ch in target_letters:
                    self.guessed.add(ch)
            return True, "Treffer ✅"
        else:
            self.wrong.add(raw.casefold())
            return True, "Leider daneben ❌"


def format_status(game: HangmanGame) -> str:
    wrong_sorted = " ".join(sorted(str(x) for x in game.wrong)) if game.wrong else "-"
    remaining = game.max_wrong - game.wrong_count
    return (
        f"Wort:   {game.masked_word()}\n"
        f"Falsch: {wrong_sorted}\n"
        f"Übrig:  {remaining}\n"
    )


# -----------------------------
# Main loop
# -----------------------------
def run_hangman(words: Sequence[str], frames: Sequence[str] = FIGURES) -> int:
    word = pick_word(words)
    game = HangmanGame(original_word=word, max_wrong=len(frames) - 1)
    term = Terminal(frames)

    while not (game.is_won or game.is_lost):
        term.draw(game.wrong_count)
        sys.stdout.write("\n" + format_status(game))
        sys.stdout.flush()

        try:
            raw = input("Rate (Buchstabe / ae/oe/ue / ss/sz): ")
        except (EOFError, KeyboardInterrupt):
            sys.stdout.write("\nAbbruch.\n")
            return 130

        applied, msg = game.guess(raw)
        if not applied:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()

    term.draw(game.wrong_count)
    sys.stdout.write("\n" + format_status(game))

    if game.is_won:
        sys.stdout.write(f"🎉 Gewonnen! Lösung (normalisiert): {game.word}\n")
        sys.stdout.write(f"   Original: {game.original_word}\n")
        return 0
    else:
        sys.stdout.write(f"💀 Verloren… Lösung (normalisiert): {game.word}\n")
        sys.stdout.write(f"   Original: {game.original_word}\n")
        return 1


def main(argv: list[str]) -> int:
    """
    Usage:
      py hangman.py [wordlist.txt]

    wordlist.txt: one word per line (UTF-8 recommended)
    """
    path = Path(argv[1]) if len(argv) > 1 else None
    words = load_words(path) if path else []
    return run_hangman(words)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
