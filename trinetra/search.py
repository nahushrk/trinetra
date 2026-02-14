"""Robust search and ranking utilities for STL/G-code discovery."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Tuple

import Levenshtein

from trinetra.logger import get_logger

logger = get_logger(__name__)

RANKING_THRESHOLD = 50
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ALNUM_SPLIT_RE = re.compile(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])")


def normalize_text(value: str) -> str:
    """Normalize text for robust matching across separators and casing."""
    lowered = unicodedata.normalize("NFKD", value or "").lower()
    no_accents = "".join(ch for ch in lowered if not unicodedata.combining(ch))
    # Unify separators so phrase and token matching can work consistently.
    return re.sub(r"[^a-z0-9]+", " ", no_accents).strip()


def tokenize_text(value: str) -> List[str]:
    """Tokenize search text while handling mixed alpha-numeric segments."""
    normalized = normalize_text(value)
    if not normalized:
        return []

    tokens: List[str] = []
    for token in _TOKEN_RE.findall(normalized):
        if not token:
            continue
        tokens.append(token)
        if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
            parts = [part for part in _ALNUM_SPLIT_RE.split(token) if part]
            tokens.extend(parts)

    # Preserve order but drop duplicates.
    seen = set()
    deduped: List[str] = []
    for token in tokens:
        if token not in seen:
            deduped.append(token)
            seen.add(token)
    return deduped


def _trigrams(value: str) -> set[str]:
    compact = normalize_text(value).replace(" ", "")
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i : i + 3] for i in range(len(compact) - 2)}


def jaccard_similarity(a: str, b: str) -> float:
    """Compute token Jaccard similarity."""
    set_a = set(tokenize_text(a))
    set_b = set(tokenize_text(b))
    union = set_a | set_b
    return (len(set_a & set_b) / len(union)) if union else 0.0


def normalized_edit_score(a: str, b: str) -> float:
    """Compute normalized edit-distance similarity score."""
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    max_len = max(len(a_norm), len(b_norm))
    if max_len == 0:
        return 0.0
    dist = Levenshtein.distance(a_norm, b_norm)
    return 1 - (dist / max_len)


def _partial_ratio(query: str, target: str) -> float:
    query_norm = normalize_text(query)
    target_norm = normalize_text(target)
    if not query_norm or not target_norm:
        return 0.0
    if query_norm in target_norm:
        return 1.0

    target_tokens = tokenize_text(target_norm)
    if not target_tokens:
        return 0.0
    return max(Levenshtein.ratio(query_norm, token) for token in target_tokens)


def _prefix_ratio(query_tokens: List[str], target_tokens: List[str]) -> float:
    if not query_tokens or not target_tokens:
        return 0.0
    matched = 0
    for query_token in query_tokens:
        if any(target_token.startswith(query_token) for target_token in target_tokens):
            matched += 1
    return matched / len(query_tokens)


def _token_typo_ratio(query_tokens: List[str], target_tokens: List[str]) -> float:
    if not query_tokens or not target_tokens:
        return 0.0
    similarities = []
    for query_token in query_tokens:
        similarities.append(max(Levenshtein.ratio(query_token, t) for t in target_tokens))
    return sum(similarities) / len(similarities)


def _trigram_jaccard(query: str, target: str) -> float:
    query_ngrams = _trigrams(query)
    target_ngrams = _trigrams(target)
    union = query_ngrams | target_ngrams
    return (len(query_ngrams & target_ngrams) / len(union)) if union else 0.0


def _adaptive_threshold(query: str) -> int:
    compact = normalize_text(query).replace(" ", "")
    size = len(compact)
    if size <= 2:
        return 82
    if size <= 3:
        return 75
    if size <= 4:
        return 63
    if size <= 7:
        return 38
    return 35


def _effective_threshold(query: str, threshold: int) -> int:
    # Respect explicit custom thresholds but improve defaults for real-world fuzzy matching.
    if threshold != RANKING_THRESHOLD:
        return threshold
    return _adaptive_threshold(query)


def compute_match_score(query: str, target: str, bm25_norm: float = 0.0) -> int:
    """
    Compute a robust hybrid score (0-100).
    Features:
    - exact/prefix token matching
    - token overlap
    - typo-tolerant token similarity
    - partial/substring match
    - trigram similarity
    - optional FTS BM25 normalization
    """
    query_norm = normalize_text(query)
    target_norm = normalize_text(target)
    if not query_norm or not target_norm:
        return 0

    query_tokens = tokenize_text(query_norm)
    target_tokens = tokenize_text(target_norm)

    token_overlap = jaccard_similarity(query_norm, target_norm)
    prefix_ratio = _prefix_ratio(query_tokens, target_tokens)
    typo_ratio = _token_typo_ratio(query_tokens, target_tokens)
    partial_ratio = _partial_ratio(query_norm, target_norm)
    trigram_ratio = _trigram_jaccard(query_norm, target_norm)
    phrase_boost = 1.0 if query_norm in target_norm else 0.0
    query_size = len(query_norm.replace(" ", ""))
    if query_size <= 3:
        # Short tokens are noisy; emphasize exact-prefix and phrase/partial matches.
        score = (
            0.45 * prefix_ratio
            + 0.10 * token_overlap
            + 0.20 * partial_ratio
            + 0.15 * phrase_boost
            + 0.10 * trigram_ratio
        )
    elif query_size <= 5:
        score = (
            0.27 * prefix_ratio
            + 0.16 * token_overlap
            + 0.20 * typo_ratio
            + 0.13 * partial_ratio
            + 0.14 * trigram_ratio
            + 0.05 * phrase_boost
            + 0.05 * max(0.0, min(1.0, bm25_norm))
        )
    else:
        score = (
            0.17 * prefix_ratio
            + 0.18 * token_overlap
            + 0.32 * typo_ratio
            + 0.10 * partial_ratio
            + 0.13 * trigram_ratio
            + 0.05 * phrase_boost
            + 0.05 * max(0.0, min(1.0, bm25_norm))
        )
    return round(max(0.0, min(1.0, score)) * 100)


def search_with_ranking(
    query: str, choices: List[str], limit: int = 25, threshold: int = RANKING_THRESHOLD
) -> List[Tuple[str, int]]:
    """Search arbitrary choices and return ranked matches."""
    if not query.strip() or not choices:
        logger.debug("Empty query or choices, returning empty results")
        return []

    effective_threshold = _effective_threshold(query, threshold)
    logger.debug(
        "[search_with_ranking] Searching '%s' in %s choices (limit=%s threshold=%s effective=%s)",
        query,
        len(choices),
        limit,
        threshold,
        effective_threshold,
    )

    scored = [(choice, compute_match_score(query, choice)) for choice in choices]
    results = [item for item in scored if item[1] >= effective_threshold]
    if not results:
        # Fallback: return top-scored candidates even if below threshold.
        results = sorted(scored, key=lambda item: item[1], reverse=True)[:limit]
        return [item for item in results if item[1] > 0]

    results.sort(key=lambda item: item[1], reverse=True)
    return results[:limit]


def build_fts_query(query: str, max_terms: int = 8) -> str:
    """Build a prefix-query expression for SQLite FTS5 retrieval."""
    tokens = [token for token in tokenize_text(query) if len(token) >= 2][:max_terms]
    if not tokens:
        return ""
    unique_tokens = list(dict.fromkeys(tokens))
    # Require all query terms but allow token-prefix matching.
    return " AND ".join(f"{token}*" for token in unique_tokens)


def rank_search_documents(
    query: str,
    documents: List[Dict[str, Any]],
    limit: int = 250,
    threshold: int = RANKING_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    Rank structured search documents.
    Expected document fields:
    - folder_name (str)
    - file_name (str, optional)
    - rel_path (str, optional)
    - bm25 (float, optional)
    """
    if not query.strip() or not documents:
        return []

    bm25_values = [doc.get("bm25") for doc in documents if isinstance(doc.get("bm25"), (int, float))]
    bm25_min = min(bm25_values) if bm25_values else None
    bm25_max = max(bm25_values) if bm25_values else None

    effective_threshold = _effective_threshold(query, threshold)
    scored_documents: List[Dict[str, Any]] = []

    for document in documents:
        target_parts = [
            str(document.get("folder_name") or ""),
            str(document.get("file_name") or ""),
            str(document.get("rel_path") or ""),
        ]
        target_text = " ".join(part for part in target_parts if part).strip()
        if not target_text:
            continue

        bm25_norm = 0.0
        raw_bm25 = document.get("bm25")
        if (
            bm25_min is not None
            and bm25_max is not None
            and isinstance(raw_bm25, (int, float))
            and bm25_max > bm25_min
        ):
            # Lower BM25 rank is better; invert to [0,1].
            bm25_norm = (bm25_max - float(raw_bm25)) / (bm25_max - bm25_min)

        score = compute_match_score(query, target_text, bm25_norm=bm25_norm)
        if score >= effective_threshold:
            ranked = dict(document)
            ranked["score"] = score
            scored_documents.append(ranked)

    if not scored_documents:
        # If threshold removed everything, return best positive-score docs.
        fallback_ranked = []
        for document in documents:
            target_text = " ".join(
                part
                for part in [
                    str(document.get("folder_name") or ""),
                    str(document.get("file_name") or ""),
                    str(document.get("rel_path") or ""),
                ]
                if part
            )
            score = compute_match_score(query, target_text)
            if score > 0:
                ranked = dict(document)
                ranked["score"] = score
                fallback_ranked.append(ranked)
        fallback_ranked.sort(key=lambda item: item["score"], reverse=True)
        return fallback_ranked[:limit]

    scored_documents.sort(
        key=lambda item: (
            item.get("score", 0),
            item.get("folder_name", ""),
            item.get("file_name", ""),
        ),
        reverse=True,
    )
    return scored_documents[:limit]


def search_files_and_folders(
    query: str,
    stl_folders: List[Dict[str, Any]],
    limit: int = 25,
    threshold: int = RANKING_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Search STL folders/files and return ranked folder-level results."""
    if not query.strip():
        return stl_folders

    effective_threshold = _effective_threshold(query, threshold)
    ranked_folders: List[Dict[str, Any]] = []

    for folder in stl_folders:
        folder_name = str(folder.get("folder_name", ""))
        folder_score = compute_match_score(query, folder_name)
        files = list(folder.get("files", []))

        matched_files: List[Tuple[Dict[str, Any], int]] = []
        for file_info in files:
            file_name = str(file_info.get("file_name", ""))
            rel_path = str(file_info.get("rel_path", ""))
            score = compute_match_score(query, f"{file_name} {rel_path}")
            if score >= effective_threshold:
                matched_files.append((file_info, score))

        top_file_score = max((score for _, score in matched_files), default=0)
        top_folder_score = max(folder_score, top_file_score)
        if top_folder_score < effective_threshold:
            continue

        result_folder = dict(folder)
        if folder_score >= effective_threshold:
            # Strong folder-name hit keeps all files.
            pass
        else:
            matched_files.sort(key=lambda item: item[1], reverse=True)
            result_folder["files"] = [file_info for file_info, _score in matched_files]

        result_folder["_score"] = top_folder_score
        ranked_folders.append(result_folder)

    ranked_folders.sort(
        key=lambda item: (item.get("_score", 0), item.get("folder_name", "")), reverse=True
    )
    output = ranked_folders[:limit]
    for folder in output:
        folder.pop("_score", None)
    return output


def search_gcode_files(
    query: str, gcode_files: List[Dict[str, Any]], limit: int = 25
) -> List[Dict[str, Any]]:
    """Search G-code files with robust fuzzy matching."""
    if not query.strip():
        return gcode_files

    ranked: List[Tuple[int, Dict[str, Any]]] = []
    threshold = _effective_threshold(query, RANKING_THRESHOLD)
    for file_info in gcode_files:
        file_name = str(file_info.get("file_name", ""))
        rel_path = str(file_info.get("rel_path", ""))
        folder_name = str(file_info.get("folder_name", ""))
        score = compute_match_score(query, f"{folder_name} {file_name} {rel_path}")
        if score >= threshold:
            ranked.append((score, file_info))

    if not ranked:
        # Fallback to best effort for very noisy query shapes.
        for file_info in gcode_files:
            file_name = str(file_info.get("file_name", ""))
            score = compute_match_score(query, file_name)
            if score > 0:
                ranked.append((score, file_info))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [file_info for _score, file_info in ranked[:limit]]
