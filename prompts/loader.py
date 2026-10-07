"""Load named prompt segments while keeping reviewer comments out of model input."""

from functools import lru_cache
from pathlib import Path
import re


_PROMPT_DIRECTORY = Path(__file__).resolve().parent
_START_PATTERN = re.compile(r"^<!-- PROMPT:([a-z0-9_]+) -->\s*$", re.MULTILINE)
_END_MARKER = "<!-- END PROMPT -->"


@lru_cache(maxsize=None)
def load_prompt(file_name: str, prompt_name: str) -> str:
    """Return one reviewed prompt body without its surrounding review comments."""
    if Path(file_name).name != file_name or not file_name.endswith(".md"):
        raise ValueError(f"Unsupported prompt file name: {file_name}")
    path = _PROMPT_DIRECTORY / file_name
    source = path.read_text(encoding="utf-8")
    matches = list(_START_PATTERN.finditer(source))
    bodies: dict[str, str] = {}
    for match in matches:
        body_start = match.end()
        body_end = source.find(_END_MARKER, body_start)
        if body_end < 0:
            raise ValueError(f"Prompt {match.group(1)} in {file_name} has no end marker")
        name = match.group(1)
        if name in bodies:
            raise ValueError(f"Duplicate prompt {name} in {file_name}")
        bodies[name] = source[body_start:body_end].strip()
    try:
        return bodies[prompt_name]
    except KeyError as exc:
        raise ValueError(f"Prompt {prompt_name} not found in {file_name}") from exc
