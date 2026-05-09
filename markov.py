"""
Markov-chain language model trained on harvested Discord messages.
Stays well under 100 MB RAM — suitable for Raspberry Pi 5 at <1 GB budget.
"""

import os
import re
import pickle
import random
import logging
from collections import defaultdict
from typing import Optional

MODEL_PATH = os.path.join(os.path.dirname(__file__), "data", "markov.pkl")

logger = logging.getLogger(__name__)

_STRIP_RE = re.compile(r"https?://\S+|<[^>]+>|[^\w\s',.!?-]")
_SPLIT_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = _STRIP_RE.sub("", text)
    return " ".join(_SPLIT_RE.split(text.strip()))


class MarkovChain:
    def __init__(self, order: int = 2):
        self.order = order
        # chain maps tuple-of-words → {next_word: count}
        self.chain: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.starts: list[tuple] = []
        self._trained = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, messages: list[str]) -> int:
        """Train (or retrain from scratch) on a list of message strings."""
        self.chain = defaultdict(lambda: defaultdict(int))
        self.starts = []

        total_tokens = 0
        for msg in messages:
            cleaned = _clean(msg)
            if not cleaned:
                continue
            words = cleaned.split()
            if len(words) < self.order + 1:
                continue
            total_tokens += len(words)
            # record valid sentence starts
            self.starts.append(tuple(words[: self.order]))
            for i in range(len(words) - self.order):
                key = tuple(words[i : i + self.order])
                next_word = words[i + self.order]
                self.chain[key][next_word] += 1

        self._trained = bool(self.starts)
        logger.info(
            "Markov model trained on %d messages / %d tokens / %d unique states",
            len(messages),
            total_tokens,
            len(self.chain),
        )
        return total_tokens

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, max_words: int = 60, seed: Optional[str] = None) -> Optional[str]:
        if not self._trained or not self.starts:
            return None

        if seed:
            seed_words = seed.lower().split()
            # try to find a starting state that contains the seed word
            matching = [s for s in self.starts if any(w in s for w in seed_words)]
            state = random.choice(matching) if matching else random.choice(self.starts)
        else:
            state = random.choice(self.starts)

        words = list(state)
        for _ in range(max_words - self.order):
            options = self.chain.get(state)
            if not options:
                break
            # weighted random choice
            total = sum(options.values())
            r = random.random() * total
            cumulative = 0
            chosen = None
            for word, count in options.items():
                cumulative += count
                if r <= cumulative:
                    chosen = word
                    break
            if chosen is None:
                break
            words.append(chosen)
            state = tuple(words[-self.order :])

            # natural sentence end
            if chosen.endswith((".", "!", "?")):
                break

        return " ".join(words) if len(words) > self.order else None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str = MODEL_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"order": self.order, "chain": dict(self.chain), "starts": self.starts}, f)
        size_kb = os.path.getsize(path) // 1024
        logger.info("Markov model saved to %s (%d KB)", path, size_kb)

    @classmethod
    def load(cls, path: str = MODEL_PATH) -> Optional["MarkovChain"]:
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            data = pickle.load(f)
        m = cls(order=data["order"])
        m.chain = defaultdict(lambda: defaultdict(int), data["chain"])
        m.starts = data["starts"]
        m._trained = bool(m.starts)
        logger.info("Markov model loaded from %s (%d states)", path, len(m.chain))
        return m
