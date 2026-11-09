"""Sentence boundary parser with Unicode sentinel shielding for HUD streaming text cards.

Adapted from Project IA for Project PA (ADR-006):
- Uses Unicode sentinel `\\uE000` to shield abbreviations, initials, decimals, and ellipses.
- Formats streaming text tokens into glanceable, high-contrast HUD cards for 640x200 MicroLED display.
"""

from __future__ import annotations
import re
from typing import List, Optional

SENTINEL_DOT = "\uE000"

# Common abbreviations to shield
_ABBREVIATIONS = (
    r"Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|vs|"
    r"approx|apt|dept|est|govt|inc|ltd|corp|vol|rev|hon|gen|col|maj|capt|lt|sgt|rep|sen"
)
_ABBREVIATION_PATTERN = re.compile(rf"\b({_ABBREVIATIONS})\.", re.IGNORECASE)

# etc. abbreviation: shielded when NOT followed by a capital letter
_ETC_PATTERN = re.compile(r"\betc\.(?!\s+[A-Z])", re.IGNORECASE)

# Multi-dot abbreviations (e.g., e.g., i.e., D.C., U.S.)
_MULTI_DOT_ABBREVIATIONS = re.compile(r"\b([eE]\.[gG]\.|[iI]\.[eE]\.|[dD]\.[cC]\.|[uU]\.[sS]\.)")

# Decimal numbers (e.g., 3.14, 12.5)
_DECIMAL_PATTERN = re.compile(r"(?<=\d)\.(?=\d)")

# Ellipses (... or ..)
_ELLIPSIS_PATTERN = re.compile(r"\.{2,}")

_SENTENCE_STARTERS = {
    "He", "She", "It", "They", "We", "You", "I",
    "The", "This", "That", "These", "Those", "There",
    "Then", "When", "What", "Who", "Why", "How", "Where",
    "If", "As", "In", "On", "At", "But", "And", "So", "However", "Meanwhile"
}

_LABEL_WORDS = {
    "Sentence", "Section", "Chapter", "Paragraph", "Part",
    "Step", "Option", "Item", "Exhibit", "Figure", "Table",
    "Phase", "Track", "Appendix", "Rule"
}

_INITIAL_PAIR_PATTERN = re.compile(r"\b([A-Z])\.(?=\s+[A-Z]\.)")
_INITIAL_NAME_PATTERN = re.compile(r"(?:(\b[A-Za-z]+)\s+)?\b([A-Z])\.\s+([A-Z][a-z]+)")

# Sentence boundary regex with lookbehinds and lookaheads
_SENTENCE_BOUNDARY = re.compile(
    r'(?:(?<=[.!?]["\'”’])|(?<=["\'”’][.!?])|(?<=[.!?]))\s+(?=[A-Z0-9"\'“‘\U00010000-\U0010ffff\u2600-\u27ff])'
)


def _shield_tokens(text: str) -> str:
    """Shields periods in abbreviations, initials, decimals, and ellipses with sentinel character."""
    text = _ELLIPSIS_PATTERN.sub(lambda m: SENTINEL_DOT * len(m.group(0)), text)
    text = _DECIMAL_PATTERN.sub(SENTINEL_DOT, text)
    text = _MULTI_DOT_ABBREVIATIONS.sub(lambda m: m.group(0).replace(".", SENTINEL_DOT), text)
    text = _ABBREVIATION_PATTERN.sub(lambda m: m.group(1) + SENTINEL_DOT, text)
    text = _ETC_PATTERN.sub("etc" + SENTINEL_DOT, text)
    text = _INITIAL_PAIR_PATTERN.sub(lambda m: m.group(1) + SENTINEL_DOT, text)

    def _shield_initial_name(match: re.Match) -> str:
        prev_word = match.group(1) or ""
        initial = match.group(2)
        next_word = match.group(3)
        if prev_word in _LABEL_WORDS or next_word in _LABEL_WORDS or next_word in _SENTENCE_STARTERS:
            return match.group(0)
        prefix = f"{prev_word} " if prev_word else ""
        return f"{prefix}{initial}{SENTINEL_DOT} {next_word}"

    text = _INITIAL_NAME_PATTERN.sub(_shield_initial_name, text)
    return text


def _unshield_tokens(text: str) -> str:
    """Restores shielded sentinels back to original period characters."""
    return text.replace(SENTINEL_DOT, ".")


def split_sentences(text: str) -> List[str]:
    """Splits arbitrary text into clean sentences, preserving abbreviations and initials."""
    if not text:
        return []

    lines = text.splitlines()
    all_sentences: List[str] = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        shielded = _shield_tokens(line_stripped)
        raw_sentences = _SENTENCE_BOUNDARY.split(shielded)
        for s in raw_sentences:
            cleaned = _unshield_tokens(s).strip()
            if cleaned:
                all_sentences.append(cleaned)

    return all_sentences


class StreamingSentenceAccumulator:
    """Accumulates streaming LLM tokens and yields complete sentences or glanceable HUD chunks.
    
    Ensures that streaming agent responses are rendered in readable, glanceable blocks on the
    640x200 MicroLED display (max characters per HUD card ~100 characters).
    """

    def __init__(self, max_card_chars: int = 100):
        self.buffer = ""
        self.max_card_chars = max_card_chars

    def feed(self, token_delta: str) -> List[str]:
        """Feed a new streaming token delta and return any completed sentences/chunks."""
        self.buffer += token_delta
        ready_chunks: List[str] = []

        # Check if we have sentence boundaries
        shielded = _shield_tokens(self.buffer)
        parts = _SENTENCE_BOUNDARY.split(shielded)

        if len(parts) > 1:
            # All parts except the last one are fully bounded complete sentences
            for p in parts[:-1]:
                sentence = _unshield_tokens(p).strip()
                if sentence:
                    ready_chunks.extend(self._format_card(sentence))

            # The last part remains in the buffer (unshielded)
            self.buffer = _unshield_tokens(parts[-1])
        else:
            # If buffer exceeds max card chars at a word boundary, emit it as a teleprompter chunk
            if len(self.buffer) >= self.max_card_chars:
                space_idx = self.buffer.rfind(" ", 0, self.max_card_chars)
                if space_idx != -1:
                    chunk = self.buffer[:space_idx].strip()
                    self.buffer = self.buffer[space_idx:].strip()
                    if chunk:
                        ready_chunks.append(chunk)

        return ready_chunks

    def flush(self) -> List[str]:
        """Flushes any remaining text in the buffer at the end of the streaming generation."""
        rem = self.buffer.strip()
        self.buffer = ""
        if rem:
            return self._format_card(rem)
        return []

    def _format_card(self, text: str) -> List[str]:
        """Splits long sentences into glanceable HUD lines if exceeding max width."""
        if len(text) <= self.max_card_chars:
            return [text]

        words = text.split()
        chunks: List[str] = []
        curr: List[str] = []
        curr_len = 0

        for w in words:
            if curr_len + len(w) + 1 > self.max_card_chars and curr:
                chunks.append(" ".join(curr))
                curr = [w]
                curr_len = len(w)
            else:
                curr.append(w)
                curr_len += len(w) + 1

        if curr:
            chunks.append(" ".join(curr))

        return chunks
