"""
Advanced fuzzy search using hybrid scoring (Jaccard + Edit Distance)
"""

import re
from typing import List, Tuple, Dict, Any
import Levenshtein

from trinetra.logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

RANKING_THRESHOLD = 50


def jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two strings"""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def normalized_edit_score(a: str, b: str) -> float:
    """Compute normalized edit distance similarity score"""
    dist = Levenshtein.distance(a.lower(), b.lower())
    max_len = max(len(a), len(b))
    return 1 - (dist / max_len) if max_len > 0 else 0.0


def compute_match_score(query: str, target: str) -> int:
    """
    Compute hybrid match score (0-100) using:
    - Jaccard similarity (token-based)
    - Normalized edit distance (character-based)
    - Substring boost
    """
    jaccard = jaccard_similarity(query, target)
    edit_sim = normalized_edit_score(query, target)
    substring_boost = 1.0 if query.lower() in target.lower() else 0.0
    # New weights: substring 0.5, jaccard 0.3, edit_sim 0.2
    score = (0.2 * edit_sim + 0.3 * jaccard + 0.5 * substring_boost) * 100
    return round(score)


def search_with_ranking(
    query: str, choices: List[str], limit: int = 25, threshold: int = RANKING_THRESHOLD
) -> List[Tuple[str, int]]:
    """
    Search with hybrid fuzzy matching using Jaccard + Edit Distance
    Args:
        query: Search query string
        choices: List of strings to search in
        limit: Maximum number of results to return
        threshold: Minimum similarity score (0-100) to include in results
    Returns:
        List of tuples (choice, score) sorted by score descending
    """
    if not query.strip() or not choices:
        logger.debug(f"Empty query or choices, returning empty results")
        return []

    logger.debug(
        f"[search_with_ranking] Searching for '{query}' in {len(choices)} choices with limit={limit}, threshold={threshold}"
    )

    results = []
    for item in choices:
        score = compute_match_score(query, item)
        logger.debug(f"[search_with_ranking] Query='{query}' vs Item='{item}' => Score={score}")
        if score >= threshold:
            results.append((item, score))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    logger.debug(f"[search_with_ranking] Results: {results[:5]} (top 5)")
    return results[:limit]


def search_files_and_folders(
    query: str,
    stl_folders: List[Dict[str, Any]],
    limit: int = 25,
    threshold: int = RANKING_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    Search through STL files and folders, returning ranked results.
    Args:
        query: Search query string
        stl_folders: List of folder dictionaries with files
        limit: Maximum number of results to return
        threshold: Minimum similarity score (0-100) to include in results
    Returns:
        List of folder dictionaries with matching files, ranked by relevance
    """
    logger.debug(
        f"[search_files_and_folders] Query='{query}', limit={limit}, threshold={threshold}"
    )
    if not query.strip():
        logger.debug("Empty query, returning all folders")
        return stl_folders

    logger.debug(f"Searching files and folders for '{query}' in {len(stl_folders)} folders")

    # Collect all searchable strings (folder names and file names)
    searchable_items = []
    folder_mapping = {}  # Map searchable item to its folder

    for folder in stl_folders:
        folder_name = folder["folder_name"]
        searchable_items.append(folder_name)
        folder_mapping[folder_name] = folder

        for file_info in folder["files"]:
            file_name = file_info["file_name"]
            searchable_items.append(file_name)
            folder_mapping[file_name] = folder

    logger.debug(f"Created searchable index with {len(searchable_items)} items")

    # Perform fuzzy search
    search_results = search_with_ranking(query, searchable_items, limit=limit, threshold=threshold)
    logger.debug(f"[search_files_and_folders] search_results: {search_results}")

    # Group results by folder and calculate folder scores
    folder_scores = {}
    for item, score in search_results:
        folder = folder_mapping[item]
        folder_name = folder["folder_name"]

        if folder_name not in folder_scores:
            folder_scores[folder_name] = {"folder": folder.copy(), "score": 0, "matches": []}

        # Use the highest score for the folder
        folder_scores[folder_name]["score"] = max(folder_scores[folder_name]["score"], score)
        folder_scores[folder_name]["matches"].append((item, score))

    # Sort folders by total score and limit results
    sorted_folders = sorted(folder_scores.values(), key=lambda x: x["score"], reverse=True)[:limit]

    logger.debug(f"Returning {len(sorted_folders)} matching folders")

    # Return folders with their files
    result_folders = []
    for folder_data in sorted_folders:
        folder = folder_data["folder"]
        matches = folder_data["matches"]

        # If folder name matches, include all files
        # If only file names match, filter to matching files
        folder_name_matches = any(item == folder["folder_name"] for item, _ in matches)

        if folder_name_matches:
            result_folders.append(folder)
        else:
            # Only include files that matched
            matching_files = []
            for file_info in folder["files"]:
                if any(item == file_info["file_name"] for item, _ in matches):
                    matching_files.append(file_info)

            if matching_files:
                result_folder = folder.copy()
                result_folder["files"] = matching_files
                result_folders.append(result_folder)

    logger.debug(
        f"[search_files_and_folders] Final result_folders: {[f['folder_name'] for f in result_folders]}"
    )
    return result_folders


def search_gcode_files(
    query: str, gcode_files: List[Dict[str, Any]], limit: int = 25
) -> List[Dict[str, Any]]:
    """
    Search through G-code files with fuzzy matching.

    Args:
        query: Search query string
        gcode_files: List of G-code file dictionaries
        limit: Maximum number of results to return

    Returns:
        List of matching G-code file dictionaries, ranked by relevance
    """
    if not query.strip():
        logger.debug("Empty query, returning all G-code files")
        return gcode_files

    logger.debug(f"Searching G-code files for '{query}' in {len(gcode_files)} files")

    # Extract file names for search
    file_names = [file_info["file_name"] for file_info in gcode_files]

    # Perform fuzzy search
    search_results = search_with_ranking(query, file_names, limit=limit)

    # Map results back to file dictionaries
    result_files = []
    for file_name, score in search_results:
        # Find the corresponding file dictionary
        for file_info in gcode_files:
            if file_info["file_name"] == file_name:
                result_files.append(file_info)
                break

    logger.debug(f"Found {len(result_files)} matching G-code files")
    return result_files


def tokenize(s: str) -> list:
    """Tokenize a string into lowercase alphanumeric words."""
    return re.findall(r"\w+", s.lower())


def search_tokens_all_match(tokens1, tokens2) -> bool:
    """Return True if all tokens in tokens1 are present in tokens2."""
    set2 = set(tokens2)
    return all(token in set2 for token in tokens1)
