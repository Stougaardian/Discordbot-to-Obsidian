import os
import re
from dataclasses import dataclass
from typing import List

from config import settings


WORD_RE = re.compile(r"[\w??????]+", re.UNICODE)


@dataclass
class Snippet:
    path: str
    heading: str
    line_start: int
    line_end: int
    excerpt: str
    score: float


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in WORD_RE.findall(text)]


def _score_line(line: str, terms: List[str]) -> int:
    line_lower = line.lower()
    score = 0
    for term in terms:
        if not term:
            continue
        score += line_lower.count(term)
    return score


def _find_heading(lines: List[str], index: int) -> str:
    if not lines:
        return "(top)"
    if index >= len(lines):
        index = len(lines) - 1
    if index < 0:
        return "(top)"
    for i in range(index, -1, -1):
        line = lines[i].strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or "(top)"
    return "(top)"


def search_vault(query: str, max_snippets: int | None = None) -> List[Snippet]:
    if not settings.vault_path:
        return []

    vault_root = os.path.abspath(settings.vault_path)
    if not os.path.isdir(vault_root):
        return []

    terms = _tokenize(query)
    if not terms:
        return []

    max_snippets = max_snippets or settings.max_snippets
    results: List[Snippet] = []

    for root, _, files in os.walk(vault_root):
        for file in files:
            if not file.lower().endswith(".md"):
                continue
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, vault_root)

            filename_score = sum(1 for term in terms if term in file.lower()) * 3

            try:
                with open(abs_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
            except UnicodeDecodeError:
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                except OSError:
                    continue
            except OSError:
                continue

            lines = content.splitlines()

            line_scores = []
            for idx, line in enumerate(lines):
                score = _score_line(line, terms)
                if score > 0:
                    line_scores.append((score, idx))

            if not line_scores and filename_score == 0:
                continue

            line_scores.sort(key=lambda item: item[0], reverse=True)
            top_hits = line_scores[:3] if line_scores else []

            for score, idx in top_hits:
                start = max(0, idx - settings.max_snippet_lines)
                end = min(len(lines) - 1, idx + settings.max_snippet_lines)
                excerpt = "\n".join(lines[start : end + 1]).strip()
                heading = _find_heading(lines, idx)
                results.append(
                    Snippet(
                        path=rel_path,
                        heading=heading,
                        line_start=start + 1,
                        line_end=end + 1,
                        excerpt=excerpt,
                        score=score + filename_score,
                    )
                )

            if not top_hits and filename_score > 0:
                snippet_end = min(len(lines), settings.max_snippet_lines * 2)
                excerpt = "\n".join(lines[:snippet_end]).strip() if lines else ""
                line_end = snippet_end if snippet_end > 0 else 1
                results.append(
                    Snippet(
                        path=rel_path,
                        heading=_find_heading(lines, 0),
                        line_start=1,
                        line_end=line_end,
                        excerpt=excerpt,
                        score=float(filename_score),
                    )
                )

    results.sort(key=lambda item: item.score, reverse=True)
    return results[:max_snippets]


def open_note(path: str, max_chars: int = 12000) -> str:
    if not settings.vault_path:
        raise FileNotFoundError("VAULT_PATH is not set")

    vault_root = os.path.abspath(settings.vault_path)
    target_path = os.path.abspath(os.path.join(vault_root, path))
    if not target_path.startswith(vault_root + os.sep):
        raise ValueError("Path traversal is not allowed")

    if not os.path.isfile(target_path):
        raise FileNotFoundError(f"Note not found: {path}")

    with open(target_path, "r", encoding="utf-8") as fh:
        content = fh.read()

    if len(content) > max_chars:
        return content[:max_chars] + "\n...\n"
    return content

