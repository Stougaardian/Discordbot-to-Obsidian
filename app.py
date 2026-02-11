import json
import os
import re
from dataclasses import asdict
from typing import Dict, List, Tuple

from fastapi import FastAPI
from pydantic import BaseModel

from config import settings
from model_runner import get_runner
from vault_tools import Snippet
from vault_index import VaultIndex, Section


IDENTITY_LINE = "Jeg hedder Dory, jeg er din digitale praktikant."
NO_INFO_LINE = "I can't find that in the vault."


class ChatRequest(BaseModel):
    user_id: str
    channel_id: str
    text: str


class ChatResponse(BaseModel):
    reply: str


class SourcesRequest(BaseModel):
    user_id: str
    channel_id: str


class SourcesResponse(BaseModel):
    sources: List[str]


class SessionStore:
    def __init__(self, path: str, max_turns: int) -> None:
        self.path = path
        self.max_turns = max_turns
        self.sessions: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
        self.sources: Dict[str, List[str]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.sessions = data.get("sessions", {})
            self.sources = data.get("sources", {})
        except (OSError, json.JSONDecodeError):
            self.sessions = {}
            self.sources = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = {"sessions": self.sessions, "sources": self.sources}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def get_session(self, user_id: str, channel_id: str) -> List[Dict[str, str]]:
        key = f"{user_id}:{channel_id}"
        return self.sessions.get(key, [])

    def update_session(self, user_id: str, channel_id: str, messages: List[Dict[str, str]]) -> None:
        key = f"{user_id}:{channel_id}"
        self.sessions[key] = messages[-self.max_turns :]
        self._save()

    def set_sources(self, user_id: str, channel_id: str, sources: List[str]) -> None:
        key = f"{user_id}:{channel_id}"
        self.sources[key] = sources
        self._save()

    def get_sources(self, user_id: str, channel_id: str) -> List[str]:
        key = f"{user_id}:{channel_id}"
        return self.sources.get(key, [])


def is_identity_question(text: str) -> bool:
    text_lower = text.lower().strip()
    patterns = [
        r"hvem er du",
        r"hvad hedder du",
        r"what's your name",
        r"what is your name",
        r"who are you",
    ]
    return any(re.search(pattern, text_lower) for pattern in patterns)


def is_info_seeking(text: str) -> bool:
    text_lower = text.lower()
    if "?" in text_lower:
        return True

    keywords = [
        "price",
        "pricing",
        "pakke",
        "package",
        "service",
        "policy",
        "politik",
        "proces",
        "process",
        "procedure",
        "how",
        "what",
        "where",
        "hvad",
        "hvordan",
        "hvor",
        "cost",
        "pris",
        "priser",
        "timeline",
        "tidslinje",
        "find",
        "show",
        "tell me",
        "forklar",
        "vis",
    ]
    return any(keyword in text_lower for keyword in keywords)


def is_price_query(text: str) -> bool:
    text_lower = text.lower()
    price_markers = (
        "pris",
        "priser",
        "price",
        "pricing",
        "pakke",
        "pakker",
        "package",
        "packages",
        "abonnement",
        "abonnements",
        "gebyr",
        "fee",
        "fees",
        "cost",
        "costs",
        "koster",
        "hvad koster",
    )
    return any(marker in text_lower for marker in price_markers)


def is_count_query(text: str) -> bool:
    text_lower = text.lower()
    count_markers = ("how many", "hvor mange", "antal", "number of", "count")
    return any(marker in text_lower for marker in count_markers)


def is_industry_query(text: str) -> bool:
    text_lower = text.lower()
    industry_markers = ("branche", "brancher", "industri", "industrier", "industries", "sektor", "sektorer")
    return any(marker in text_lower for marker in industry_markers)


def build_snippets_from_sections(sections: List[Section], max_chars: int = 1600) -> List[Snippet]:
    snippets: List[Snippet] = []
    for section in sections:
        excerpt = section.text.strip()
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars].rstrip() + "\n..."
        snippets.append(
            Snippet(
                path=section.path,
                heading=section.heading,
                line_start=section.line_start,
                line_end=section.line_end,
                excerpt=excerpt,
                score=section.score,
            )
        )
    return snippets


WORD_PATTERN = re.compile(r"[\wæøåÆØÅ]+", re.UNICODE)
PRICE_PATTERN = re.compile(r"(\d[\d\.,]*)\s*(dkk|kr\.?|\bkr\b)", re.IGNORECASE)
LABEL_STOP = {
    "pris",
    "price",
    "abonnement",
    "billedpakker",
    "certificering",
    "pakker",
    "pakken",
}
CONTINUATION_PREFIXES = ("inkl", "inkl.", "inklusive", "pr.", "pr", "per", "/")


def _clean_text(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("*", "")
    text = text.strip().strip("-:•\t ")
    return re.sub(r"\s+", " ", text).strip()


def _has_letters(text: str) -> bool:
    return re.search(r"[A-Za-zæøåÆØÅ]", text) is not None


def _is_stop_label(text: str) -> bool:
    cleaned = text.lower().strip(" :\t")
    return cleaned in LABEL_STOP


def _extract_price_from_line(line: str) -> str | None:
    match = PRICE_PATTERN.search(line)
    if not match:
        return None
    price = match.group(0).strip()
    suffix = line[match.end() :].strip()
    if suffix:
        suffix_words = suffix.split()
        if suffix_words and (
            suffix_words[0].startswith("/")
            or suffix_words[0].lower().startswith("pr")
            or suffix_words[0].lower().startswith("per")
        ):
            price = f"{price} {' '.join(suffix_words[:2])}".strip()
    return price


def _name_from_line(line: str, price: str | None) -> str:
    if not line:
        return ""
    cleaned = _clean_text(line)
    if price:
        cleaned = cleaned.replace(price, "").strip()
    cleaned = cleaned.strip("-:•\t ")
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if _is_stop_label(lowered):
        return ""
    if lowered in ("/ år", "/ aar", "/år", "pr. år", "pr år"):
        return ""
    if not _has_letters(cleaned):
        return ""
    if len(cleaned) <= 2:
        return ""
    return cleaned


def _collect_label(lines: List[str], idx: int, max_lines: int = 4) -> str:
    collected: List[str] = []
    j = idx - 1
    while j >= 0 and len(collected) < max_lines:
        raw = lines[j].strip()
        if not raw:
            if collected:
                break
            j -= 1
            continue
        if raw.startswith("#"):
            j -= 1
            continue
        candidate = _clean_text(raw)
        if not candidate:
            j -= 1
            continue
        if _is_stop_label(candidate):
            j -= 1
            continue
        collected.insert(0, candidate)
        j -= 1
    label = " ".join(collected).strip()
    return label


def _parse_table_row(line: str) -> List[str] | None:
    if "|" not in line:
        return None
    stripped = line.strip()
    if not stripped:
        return None
    if all(char in "|-: " for char in stripped):
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return [cell for cell in cells if cell]


def extract_price_items(sections: List[Section]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for section in sections:
        lines = section.text.splitlines()
        for idx, line in enumerate(lines):
            table_cells = _parse_table_row(line)
            if table_cells:
                price_cell = None
                for cell in table_cells:
                    if PRICE_PATTERN.search(cell):
                        price_cell = cell
                        break
                if price_cell:
                    price = _extract_price_from_line(price_cell)
                    name = ""
                    for cell in table_cells:
                        if cell == price_cell:
                            continue
                        candidate = _name_from_line(cell, None)
                        if candidate and not _is_stop_label(candidate):
                            name = candidate
                            break
                    if not name:
                        name = _collect_label(lines, idx)
                    if name and price:
                        items.append(
                            {
                                "name": name,
                                "price": price,
                                "path": section.path,
                                "heading": section.heading,
                                "line_start": section.line_start + max(idx - 1, 0),
                                "line_end": section.line_start + idx,
                            }
                        )
                continue

            price = _extract_price_from_line(line)
            if not price:
                continue
            name = _name_from_line(line, price)
            if not name:
                name = _collect_label(lines, idx)

            if name:
                if name.lower().startswith(CONTINUATION_PREFIXES):
                    extended = _collect_label(lines, idx, max_lines=4)
                    if extended and extended != name:
                        name = extended
                items.append(
                    {
                        "name": name,
                        "price": price,
                        "path": section.path,
                        "heading": section.heading,
                        "line_start": section.line_start + max(idx - 1, 0),
                        "line_end": section.line_start + idx,
                    }
                )

    seen = set()
    deduped: List[Dict[str, str]] = []
    for item in items:
        key = (item["path"], item["heading"], item["name"], item["price"], item["line_start"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(key=lambda item: (item["path"], item["line_start"]))
    return deduped


INCLUSION_MARKERS = ("inkl", "inkl.", "inklusive", "gratis", "medlemskab", "medlem", "uden ekstra")
PRICE_STOPWORDS = {
    "hvad",
    "hvor",
    "hvem",
    "hvordan",
    "det",
    "for",
    "til",
    "et",
    "en",
    "den",
    "der",
    "som",
    "at",
    "og",
    "the",
    "what",
    "where",
    "how",
    "does",
    "do",
    "is",
    "are",
    "a",
    "an",
    "of",
    "it",
    "cost",
    "costs",
    "koster",
    "pris",
    "priser",
    "price",
    "pricing",
    "pakke",
    "pakker",
    "package",
    "packages",
    "abonnement",
    "abonnements",
}
SHORT_KEEP = {"gln", "gtin", "gdsn", "sscc"}


def _normalize_token(token: str) -> str:
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    if token.endswith("er") and len(token) > 4:
        return token[:-2]
    if token.endswith("e") and len(token) > 4:
        return token[:-1]
    return token


def _query_tokens(query: str) -> List[str]:
    tokens: List[str] = []
    for token in WORD_PATTERN.findall(query.lower()):
        if token in PRICE_STOPWORDS:
            continue
        if len(token) < 3 and token not in SHORT_KEEP:
            continue
        normalized = _normalize_token(token)
        tokens.append(token)
        if normalized != token:
            tokens.append(normalized)
    return sorted(set(tokens))


def extract_inclusion_snippets(sections: List[Section], query: str, limit: int = 4) -> List[Snippet]:
    query_tokens = _query_tokens(query)
    if not query_tokens:
        return []

    snippets: List[Snippet] = []
    for section in sections:
        lines = section.text.splitlines()
        for idx, line in enumerate(lines):
            line_lower = line.lower()
            if not any(token in line_lower for token in query_tokens):
                continue
            if not any(marker in line_lower for marker in INCLUSION_MARKERS):
                continue
            start_idx = max(0, idx - 1)
            end_idx = min(len(lines) - 1, idx + 1)
            excerpt = "\n".join(lines[start_idx : end_idx + 1]).strip()
            snippets.append(
                Snippet(
                    path=section.path,
                    heading=section.heading,
                    line_start=section.line_start + start_idx,
                    line_end=section.line_start + end_idx,
                    excerpt=excerpt,
                    score=section.score,
                )
            )
            if len(snippets) >= limit:
                return snippets

    return snippets


def build_brancher_count_snippets() -> List[Snippet]:
    target_path = None
    for path in index.notes:
        if path.lower().endswith("gs1dk brancher index.md"):
            target_path = path
            break
    if not target_path:
        return []

    pages_section = None
    for section in index.sections:
        if section.path == target_path and section.heading.lower() == "pages":
            pages_section = section
            break
    if not pages_section:
        return []

    lines = pages_section.text.splitlines()
    list_lines = [line for line in lines if line.strip().startswith("- [[")]
    if not list_lines:
        return []

    count = len(list_lines)
    excerpt_lines = [f"Antal brancher i index: {count}"]
    excerpt_lines.extend(list_lines[: min(len(list_lines), 20)])

    return [
        Snippet(
            path=pages_section.path,
            heading=pages_section.heading,
            line_start=pages_section.line_start,
            line_end=pages_section.line_end,
            excerpt="\n".join(excerpt_lines),
            score=999.0,
        )
    ]


def build_price_snippets_from_items(items: List[Dict[str, str]]) -> List[Snippet]:
    grouped: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    for item in items:
        key = (item["path"], item["heading"])
        grouped.setdefault(key, []).append(item)

    snippets: List[Snippet] = []
    for (path, heading), group in grouped.items():
        excerpt_lines = [f"{item['name']} — {item['price']}" for item in group]
        line_start = min(int(item["line_start"]) for item in group)
        line_end = max(int(item["line_end"]) for item in group)
        snippets.append(
            Snippet(
                path=path,
                heading=heading,
                line_start=line_start,
                line_end=line_end,
                excerpt="\n".join(excerpt_lines),
                score=999.0,
            )
        )
    return snippets


def build_system_prompt(info_seeking: bool, price_query: bool = False) -> str:
    base = (
        "You are Dory. If asked who you are or your name, reply exactly: "
        f"'{IDENTITY_LINE}'."
        " You are an Obsidian-vault-grounded assistant and must not invent corporate facts."
    )
    if info_seeking:
        prompt = (
            base
            + " You will receive extracted facts from the vault. "
            + "Your job is to format those facts clearly without adding, inferring, or omitting information. "
            + "Answer only using the provided vault snippets. "
            + "If the answer is not in the snippets, reply: 'I can't find that in the vault.' "
            + "Include a Sources section with citations in this exact format: "
            + "- <path>#<heading> (lines a-b)"
        )
        if price_query:
            prompt += " When asked for prices or packages, list each package name with its price exactly as provided."
        return prompt
    return base


def format_snippets(snippets: List[Snippet]) -> List[Dict[str, str]]:
    return [asdict(snippet) for snippet in snippets]


def parse_sources(text: str) -> List[str]:
    sources = []
    if "Sources:" not in text:
        return sources
    lines = text.splitlines()
    capture = False
    for line in lines:
        if line.strip().startswith("Sources:"):
            capture = True
            continue
        if capture:
            if not line.strip():
                continue
            if line.strip().startswith("-"):
                sources.append(line.strip()[2:])
            else:
                break
    return sources


def ensure_sources(response: str, snippets: List[Snippet]) -> Tuple[str, List[str]]:
    sources = parse_sources(response)
    if sources:
        return response, sources

    base = response
    if "Sources:" in response:
        base = response.split("Sources:")[0].rstrip()

    fallback_sources = []
    for snippet in snippets[:3]:
        fallback_sources.append(
            f"{snippet.path}#{snippet.heading} (lines {snippet.line_start}-{snippet.line_end})"
        )

    if fallback_sources:
        response = base.rstrip() + "\n\nSources:\n" + "\n".join(
            f"- {src}" for src in fallback_sources
        )
    return response, fallback_sources


def is_runner_error(text: str) -> bool:
    error_markers = (
        "Local codex binary not found",
        "Local codex exec failed",
        "Local codex exec timed out",
        "OpenAI API error",
    )
    return any(marker in text for marker in error_markers)


def _select_top_paths(sections: List[Section], limit: int = 2) -> List[str]:
    scores: Dict[str, float] = {}
    for section in sections:
        scores[section.path] = scores.get(section.path, 0.0) + section.score
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [path for path, _ in ranked[:limit]]


def _rank_sections(sections: List[Section], query: str, top_k: int) -> List[Section]:
    query_lower = query.lower()
    tokens = [token for token in WORD_PATTERN.findall(query_lower) if token]
    if not tokens:
        return []
    scored: List[Section] = []
    for section in sections:
        text_lower = section.text.lower()
        heading_lower = section.heading.lower()
        path_lower = section.path.lower()
        score = 0.0
        for token in tokens:
            score += text_lower.count(token)
            score += 3.0 * heading_lower.count(token)
            score += 2.0 * path_lower.count(token)
        if query_lower in text_lower:
            score += 8.0
        if score > 0:
            scored.append(
                Section(
                    path=section.path,
                    heading=section.heading,
                    line_start=section.line_start,
                    line_end=section.line_end,
                    text=section.text,
                    score=score,
                )
            )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:top_k]


def _price_candidate_sections(query: str, max_sections: int) -> Tuple[List[Section], List[str]]:
    alias_paths = index.find_paths_by_alias(query)
    if alias_paths:
        return index.sections_for_paths(alias_paths), alias_paths

    reduced_query = " ".join(_query_tokens(query)) or query
    scored_sections = index.find_sections(reduced_query, top_k=max_sections)
    if not scored_sections:
        return [], []
    top_paths = _select_top_paths(scored_sections, limit=2)
    expanded = index.sections_for_paths(top_paths)
    return expanded or scored_sections, []


def filter_price_items(items: List[Dict[str, str]], query: str) -> List[Dict[str, str]]:
    query_tokens = _query_tokens(query)
    if not query_tokens:
        return items
    filtered = [
        item
        for item in items
        if any(token in item["name"].lower() for token in query_tokens)
    ]
    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in filtered:
        key = (item["name"].lower(), item["price"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


app = FastAPI()
runner = get_runner()
store = SessionStore(settings.session_path, settings.session_max_turns)
index = VaultIndex(settings.vault_path)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    text = request.text.strip()
    if not text:
        return ChatResponse(reply="")

    if is_identity_question(text):
        reply = IDENTITY_LINE
        _update_history(request, text, reply)
        return ChatResponse(reply=reply)

    info_seeking = is_info_seeking(text)
    price_query = is_price_query(text)

    snippets: List[Snippet] = []
    if info_seeking:
        if not index.sections and settings.vault_path:
            index.build()
        if is_count_query(text) and is_industry_query(text):
            snippets = build_brancher_count_snippets()
            if not snippets:
                reply = NO_INFO_LINE
                _update_history(request, text, reply)
                return ChatResponse(reply=reply)
        elif price_query:
            candidate_sections, alias_paths = _price_candidate_sections(
                text, settings.max_snippets * 4
            )
            if not candidate_sections:
                reply = NO_INFO_LINE
                _update_history(request, text, reply)
                return ChatResponse(reply=reply)
            price_items = extract_price_items(candidate_sections)
            if price_items and not alias_paths:
                price_items = filter_price_items(price_items, text)
            if not price_items:
                inclusion_snippets = extract_inclusion_snippets(candidate_sections, text)
                if not inclusion_snippets:
                    reply = NO_INFO_LINE
                    _update_history(request, text, reply)
                    return ChatResponse(reply=reply)
                snippets = inclusion_snippets
                price_query = False
            else:
                snippets = build_price_snippets_from_items(price_items)
        else:
            alias_paths = index.find_paths_by_alias(text)
            if alias_paths:
                candidate_sections = _rank_sections(
                    index.sections_for_paths(alias_paths), text, settings.max_snippets
                )
            else:
                candidate_sections = index.find_sections(text, top_k=settings.max_snippets)
            if not candidate_sections:
                reply = NO_INFO_LINE
                _update_history(request, text, reply)
                return ChatResponse(reply=reply)
            snippets = build_snippets_from_sections(candidate_sections)

    session_messages = store.get_session(request.user_id, request.channel_id)
    conversation = session_messages + [{"role": "user", "content": text}]
    system_prompt = build_system_prompt(info_seeking, price_query)

    response_text = runner.run(system_prompt, conversation, format_snippets(snippets))

    if info_seeking:
        if response_text.strip() == NO_INFO_LINE:
            _update_history(request, text, response_text)
            return ChatResponse(reply=response_text)
        if is_runner_error(response_text):
            _update_history(request, text, response_text)
            return ChatResponse(reply=response_text)
        if "Sources:" not in response_text:
            stronger_prompt = system_prompt + " You MUST include a Sources section with citations."
            response_text = runner.run(stronger_prompt, conversation, format_snippets(snippets))
        response_text, sources = ensure_sources(response_text, snippets)
        store.set_sources(request.user_id, request.channel_id, sources)

    _update_history(request, text, response_text)
    return ChatResponse(reply=response_text)


@app.post("/sources", response_model=SourcesResponse)
async def sources(request: SourcesRequest) -> SourcesResponse:
    return SourcesResponse(sources=store.get_sources(request.user_id, request.channel_id))


def _update_history(request: ChatRequest, user_text: str, reply: str) -> None:
    history = store.get_session(request.user_id, request.channel_id)
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    store.update_session(request.user_id, request.channel_id, history)

