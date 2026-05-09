"""
Optional llama.cpp backend using llama-cpp-python.

Uses TinyLlama-1.1B-Chat Q4_K_M (~638 MB) — fits on Raspberry Pi 5 under the 1 GB budget.

To enable:
  1. pip install llama-cpp-python
  2. Download the model:
       wget https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
  3. Set model_backend="llama" and llama_model_path="/path/to/model.gguf" in config.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_llm = None          # lazy-loaded llama_cpp.Llama instance
_persona: str = ""   # few-shot persona built from sample messages


def _load_llama(model_path: str, n_ctx: int = 512):
    global _llm
    if _llm is not None:
        return
    try:
        from llama_cpp import Llama  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "llama-cpp-python is not installed. Run: pip install llama-cpp-python"
        ) from exc

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")

    _llm = Llama(
        model_path=model_path,
        n_ctx=n_ctx,
        n_threads=4,
        use_mmap=True,
        use_mlock=False,
        verbose=False,
    )
    logger.info("llama.cpp model loaded from %s", model_path)


def build_persona(sample_messages: list[str], max_samples: int = 20):
    """Store a handful of real messages as a persona for few-shot prompting."""
    global _persona
    samples = sample_messages[:max_samples]
    _persona = "\n".join(f"- {m}" for m in samples)


def generate(
    model_path: str,
    seed_text: Optional[str],
    max_tokens: int = 120,
) -> Optional[str]:
    _load_llama(model_path)

    persona_block = (
        f"Here are some example messages from this person:\n{_persona}\n\n"
        if _persona
        else ""
    )
    seed_clause = f' Incorporate the topic: "{seed_text}".' if seed_text else ""
    prompt = (
        f"<|system|>\nYou are mimicking a Discord user's writing style.{seed_clause}\n"
        f"{persona_block}"
        f"<|user|>\nWrite one short Discord message in their style.\n<|assistant|>\n"
    )

    try:
        output = _llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.85,
            top_p=0.9,
            repeat_penalty=1.1,
            stop=["<|user|>", "<|system|>", "\n\n"],
        )
        text = output["choices"][0]["text"].strip()
        return text or None
    except Exception as exc:
        logger.error("llama generation error: %s", exc)
        return None
