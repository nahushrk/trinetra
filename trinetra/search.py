"""
Search functionality for Trinetra using thefuzz library for fuzzy matching and ranking
"""

import re
from typing import List, Tuple, Dict, Any
from thefuzz import process

from trinetra.logger import get_logger

# Get logger for this module
logger = get_logger(__name__)


def tokenize(text: str) -> List[str]:
    """Tokenize text into words, removing special characters."""
    return [word.lower() for word in re.split(r"\W+|_", text) if word]


def search_with_ranking(
    query: str, choices: List[str], limit: int = 25, threshold: int = 75
) -> List[Tuple[str, int]]:
    """
    Search with fuzzy matching and ranking using thefuzz.

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
        f"Searching for '{query}' in {len(choices)} choices with limit={limit}, threshold={threshold}"
    )

    # Use thefuzz process.extract for fuzzy matching
    results = process.extract(query.lower(), choices, limit=limit)

    # Filter by threshold and sort by score descending (highest first)
    filtered_results = [(choice, score) for choice, score in results if score >= threshold]
    filtered_results.sort(key=lambda x: x[1], reverse=True)

    logger.debug(f"Found {len(filtered_results)} results above threshold {threshold}")
    return filtered_results


def search_files_and_folders(
    query: str, stl_folders: List[Dict[str, Any]], limit: int = 25
) -> List[Dict[str, Any]]:
    """
    Search through STL files and folders, returning ranked results.

    Args:
        query: Search query string
        stl_folders: List of folder dictionaries with files
        limit: Maximum number of results to return

    Returns:
        List of folder dictionaries with matching files, ranked by relevance
    """
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
    search_results = search_with_ranking(query, searchable_items, limit=limit)

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


# Legacy functions for backward compatibility
def search_tokens_all_match(query_tokens: List[str], target_tokens: List[str]) -> bool:
    """Legacy function for backward compatibility."""
    return all(token in target_tokens for token in query_tokens)


def search_tokens(query_tokens: List[str], target_tokens: List[str]) -> bool:
    """Legacy function for backward compatibility."""
    for query in query_tokens:
        if any(query == target or target.startswith(query) for target in target_tokens):
            return True
    return False
