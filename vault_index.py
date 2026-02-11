import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

WORD_RE = re.compile(r"[\wæøåÆØÅ]+", re.UNICODE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")


@dataclass
class Section:
    path: str
    heading: str
    line_start: int
    line_end: int
    text: str
    score: float = 0.0


@dataclass
class NoteMeta:
    path: str
    title: str
    aliases: List[str]


class VaultIndex:
    def __init__(self, vault_root: str | None) -> None:
        self.vault_root = os.path.abspath(vault_root) if vault_root else None
        self.sections: List[Section] = []
        self.notes: Dict[str, NoteMeta] = {}
        self._last_built = 0.0
        if self.vault_root:
            self.build()

    def build(self) -> None:
        if not self.vault_root or not os.path.isdir(self.vault_root):
            self.sections = []
            self.notes = {}
            return

        sections: List[Section] = []
        notes: Dict[str, NoteMeta] = {}

        for root, _, files in os.walk(self.vault_root):
            for file in files:
                if not file.lower().endswith(".md"):
                    continue
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, self.vault_root)
                content = self._read_file(abs_path)
                lines = content.splitlines()

                title = self._detect_title(lines, file)
                aliases = self._build_aliases(title, file)
                notes[rel_path] = NoteMeta(path=rel_path, title=title, aliases=aliases)

                sections.extend(self._split_sections(rel_path, lines))

        self.sections = sections
        self.notes = notes
        self._last_built = time.time()

    def _read_file(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read()
        except OSError:
            return ""

    def _detect_title(self, lines: List[str], filename: str) -> str:
        for line in lines:
            match = HEADING_RE.match(line.strip())
            if match:
                title = match.group(2).strip()
                if title:
                    return title
        return os.path.splitext(filename)[0].replace("_", " ").replace("-", " ")

    def _split_camel(self, text: str) -> str:
        text = re.sub(r"([a-zæøå])([A-ZÆØÅ])", r"\1 \2", text)
        text = re.sub(r"([0-9])([A-Za-zæøåÆØÅ])", r"\1 \2", text)
        text = re.sub(r"([A-Za-zæøåÆØÅ])([0-9])", r"\1 \2", text)
        return text

    def _build_aliases(self, title: str, filename: str) -> List[str]:
        base = os.path.splitext(filename)[0]
        variants = {
            title,
            base,
            base.replace("-", " "),
            base.replace("_", " "),
        }
        expanded: set[str] = set()
        for variant in variants:
            if not variant:
                continue
            expanded.add(variant)
            expanded.add(self._split_camel(variant))

        aliases: set[str] = set()
        for variant in expanded:
            cleaned = re.sub(r"\s+", " ", variant).strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            aliases.add(lowered)
            tokens = WORD_RE.findall(lowered)
            if len(tokens) >= 2 and tokens[0] == "gs" and tokens[1].isdigit():
                tokens = [f"gs{tokens[1]}"] + tokens[2:]
            if len(tokens) >= 2:
                aliases.add(" ".join(tokens[:2]))
            if len(tokens) >= 3:
                aliases.add(" ".join(tokens[:3]))
            if tokens and tokens[0].startswith("gs1") and len(tokens) >= 2:
                aliases.add(" ".join(tokens[1:3]))

        return sorted(aliases)

    def _split_sections(self, path: str, lines: List[str]) -> List[Section]:
        if not lines:
            return []

        boundaries: List[Tuple[int, str]] = []
        for idx, line in enumerate(lines):
            match = HEADING_RE.match(line.strip())
            if match:
                heading = match.group(2).strip() or "(top)"
                boundaries.append((idx, heading))

        sections: List[Section] = []
        if not boundaries:
            sections.append(
                Section(
                    path=path,
                    heading="(top)",
                    line_start=1,
                    line_end=len(lines),
                    text="\n".join(lines).strip(),
                )
            )
            return sections

        # Section before first heading
        if boundaries[0][0] > 0:
            sections.append(
                Section(
                    path=path,
                    heading="(top)",
                    line_start=1,
                    line_end=boundaries[0][0],
                    text="\n".join(lines[: boundaries[0][0]]).strip(),
                )
            )

        for index, (start_idx, heading) in enumerate(boundaries):
            end_idx = boundaries[index + 1][0] - 1 if index + 1 < len(boundaries) else len(lines) - 1
            section_lines = lines[start_idx : end_idx + 1]
            sections.append(
                Section(
                    path=path,
                    heading=heading,
                    line_start=start_idx + 1,
                    line_end=end_idx + 1,
                    text="\n".join(section_lines).strip(),
                )
            )
        return sections

    def find_sections(self, query: str, top_k: int = 5) -> List[Section]:
        query_lower = query.lower()
        tokens = [t.lower() for t in WORD_RE.findall(query_lower)]
        if not tokens:
            return []

        results: List[Section] = []
        for section in self.sections:
            note_meta = self.notes.get(section.path)
            note_boost = 0.0
            if note_meta and any(alias in query_lower for alias in note_meta.aliases):
                note_boost += 20.0
            score = note_boost + self._score_section(section, tokens, query_lower)
            if score > 0:
                results.append(
                    Section(
                        path=section.path,
                        heading=section.heading,
                        line_start=section.line_start,
                        line_end=section.line_end,
                        text=section.text,
                        score=score,
                    )
                )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    def _score_section(self, section: Section, tokens: List[str], query_lower: str) -> float:
        text_lower = section.text.lower()
        heading_lower = section.heading.lower()
        path_lower = section.path.lower()
        score = 0.0
        for token in tokens:
            if not token:
                continue
            score += text_lower.count(token)
            score += 3.0 * heading_lower.count(token)
            score += 2.0 * path_lower.count(token)
        if query_lower in text_lower:
            score += 8.0
        return score

    def find_paths_by_alias(self, query: str) -> List[str]:
        query_lower = query.lower()
        matches = []
        for path, meta in self.notes.items():
            if any(alias in query_lower for alias in meta.aliases):
                matches.append(path)
        return matches

    def sections_for_paths(self, paths: List[str]) -> List[Section]:
        path_set = set(paths)
        return [section for section in self.sections if section.path in path_set]
