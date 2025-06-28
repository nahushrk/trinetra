"""
Comprehensive tests for search.py module
Covers all functions and edge cases for fuzzy search functionality
"""

import unittest
from unittest.mock import patch, MagicMock
from trinetra import search


class TestSearchFunctions(unittest.TestCase):
    """Test cases for search module functions"""

    def test_tokenize_basic(self):
        """Test basic tokenization functionality"""
        text = "Braided_Grass_Vases/files-2024!@#$%^&*()"
        tokens = search.tokenize(text)
        expected = ["braided", "grass", "vases", "files", "2024"]
        self.assertEqual(tokens, expected)

    def test_tokenize_empty_string(self):
        """Test tokenization with empty string"""
        tokens = search.tokenize("")
        self.assertEqual(tokens, [])

    def test_tokenize_whitespace_only(self):
        """Test tokenization with whitespace only"""
        tokens = search.tokenize("   \t\n  ")
        self.assertEqual(tokens, [])

    def test_tokenize_special_characters(self):
        """Test tokenization with special characters"""
        text = "test@example.com_123!@#$%^&*()"
        tokens = search.tokenize(text)
        expected = ["test", "example", "com", "123"]
        self.assertEqual(tokens, expected)

    def test_tokenize_mixed_case(self):
        """Test tokenization preserves case conversion"""
        text = "TestFile_123"
        tokens = search.tokenize(text)
        expected = ["testfile", "123"]
        self.assertEqual(tokens, expected)

    @patch("trinetra.search.process.extract")
    def test_search_with_ranking_success(self, mock_extract):
        """Test successful search with ranking"""
        mock_extract.return_value = [
            ("test_file.gcode", 95),
            ("other_file.gcode", 85),
            ("low_match.gcode", 60),
        ]

        query = "test"
        choices = ["test_file.gcode", "other_file.gcode", "low_match.gcode"]
        results = search.search_with_ranking(query, choices, limit=10, threshold=75)

        expected = [("test_file.gcode", 95), ("other_file.gcode", 85)]
        self.assertEqual(results, expected)
        mock_extract.assert_called_once_with("test", choices, limit=10)

    def test_search_with_ranking_empty_query(self):
        """Test search with empty query"""
        results = search.search_with_ranking("", ["file1", "file2"])
        self.assertEqual(results, [])

    def test_search_with_ranking_empty_choices(self):
        """Test search with empty choices"""
        results = search.search_with_ranking("test", [])
        self.assertEqual(results, [])

    @patch("trinetra.search.process.extract")
    def test_search_with_ranking_below_threshold(self, mock_extract):
        """Test search where all results are below threshold"""
        mock_extract.return_value = [("file1.gcode", 50), ("file2.gcode", 30)]

        results = search.search_with_ranking("test", ["file1", "file2"], threshold=75)
        self.assertEqual(results, [])

    @patch("trinetra.search.process.extract")
    def test_search_with_ranking_custom_limit(self, mock_extract):
        """Test search with custom limit"""
        mock_extract.return_value = [("file1.gcode", 95), ("file2.gcode", 85), ("file3.gcode", 75)]

        results = search.search_with_ranking(
            "test", ["file1", "file2", "file3"], limit=2, threshold=70
        )
        expected = [("file1.gcode", 95), ("file2.gcode", 85), ("file3.gcode", 75)]
        self.assertEqual(results, expected)

    def test_search_files_and_folders_empty_query(self):
        """Test search files and folders with empty query"""
        stl_folders = [{"folder_name": "test_folder", "files": [{"file_name": "test.stl"}]}]

        results = search.search_files_and_folders("", stl_folders)
        self.assertEqual(results, stl_folders)

    @patch("trinetra.search.search_with_ranking")
    def test_search_files_and_folders_folder_match(self, mock_search):
        """Test search where folder name matches"""
        mock_search.return_value = [("test_folder", 95)]

        stl_folders = [{"folder_name": "test_folder", "files": [{"file_name": "test.stl"}]}]

        results = search.search_files_and_folders("test", stl_folders)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["folder_name"], "test_folder")
        self.assertEqual(len(results[0]["files"]), 1)  # All files included

    @patch("trinetra.search.search_with_ranking")
    def test_search_files_and_folders_file_match(self, mock_search):
        """Test search where only file name matches"""
        mock_search.return_value = [("test.stl", 95)]

        stl_folders = [
            {
                "folder_name": "other_folder",
                "files": [{"file_name": "test.stl"}, {"file_name": "other.stl"}],
            }
        ]

        results = search.search_files_and_folders("test", stl_folders)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["folder_name"], "other_folder")
        self.assertEqual(len(results[0]["files"]), 1)  # Only matching file
        self.assertEqual(results[0]["files"][0]["file_name"], "test.stl")

    @patch("trinetra.search.search_with_ranking")
    def test_search_files_and_folders_multiple_matches(self, mock_search):
        """Test search with multiple matches in same folder"""
        mock_search.return_value = [("test_folder", 90), ("test.stl", 95), ("other.stl", 85)]

        stl_folders = [
            {
                "folder_name": "test_folder",
                "files": [
                    {"file_name": "test.stl"},
                    {"file_name": "other.stl"},
                    {"file_name": "unrelated.stl"},
                ],
            }
        ]

        results = search.search_files_and_folders("test", stl_folders)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["folder_name"], "test_folder")
        # Should include all files since folder name matched
        self.assertEqual(len(results[0]["files"]), 3)

    def test_search_gcode_files_empty_query(self):
        """Test search gcode files with empty query"""
        gcode_files = [
            {"file_name": "test.gcode", "metadata": {}},
            {"file_name": "other.gcode", "metadata": {}},
        ]

        results = search.search_gcode_files("", gcode_files)
        self.assertEqual(results, gcode_files)

    @patch("trinetra.search.search_with_ranking")
    def test_search_gcode_files_success(self, mock_search):
        """Test successful gcode file search"""
        mock_search.return_value = [("test.gcode", 95)]

        gcode_files = [
            {"file_name": "test.gcode", "metadata": {"time": "1h"}},
            {"file_name": "other.gcode", "metadata": {"time": "2h"}},
        ]

        results = search.search_gcode_files("test", gcode_files)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file_name"], "test.gcode")
        self.assertEqual(results[0]["metadata"]["time"], "1h")

    @patch("trinetra.search.search_with_ranking")
    def test_search_gcode_files_no_matches(self, mock_search):
        """Test gcode search with no matches"""
        mock_search.return_value = []

        gcode_files = [
            {"file_name": "test.gcode", "metadata": {}},
            {"file_name": "other.gcode", "metadata": {}},
        ]

        results = search.search_gcode_files("nonexistent", gcode_files)
        self.assertEqual(results, [])

    def test_search_tokens_all_match_true(self):
        """Test search_tokens_all_match returns True when all tokens match"""
        query_tokens = ["test", "file"]
        target_tokens = ["test", "file", "gcode"]
        result = search.search_tokens_all_match(query_tokens, target_tokens)
        self.assertTrue(result)

    def test_search_tokens_all_match_false(self):
        """Test search_tokens_all_match returns False when not all tokens match"""
        query_tokens = ["test", "file", "nonexistent"]
        target_tokens = ["test", "file", "gcode"]
        result = search.search_tokens_all_match(query_tokens, target_tokens)
        self.assertFalse(result)

    def test_search_tokens_all_match_empty_query(self):
        """Test search_tokens_all_match with empty query"""
        query_tokens = []
        target_tokens = ["test", "file"]
        result = search.search_tokens_all_match(query_tokens, target_tokens)
        self.assertTrue(result)  # Empty query should match everything

    def test_search_tokens_all_match_empty_target(self):
        """Test search_tokens_all_match with empty target"""
        query_tokens = ["test"]
        target_tokens = []
        result = search.search_tokens_all_match(query_tokens, target_tokens)
        self.assertFalse(result)

    def test_search_tokens_true(self):
        """Test search_tokens returns True when any token matches"""
        query_tokens = ["test", "nonexistent"]
        target_tokens = ["test", "file", "gcode"]
        result = search.search_tokens(query_tokens, target_tokens)
        self.assertTrue(result)

    def test_search_tokens_false(self):
        """Test search_tokens returns False when no tokens match"""
        query_tokens = ["nonexistent", "missing"]
        target_tokens = ["test", "file", "gcode"]
        result = search.search_tokens(query_tokens, target_tokens)
        self.assertFalse(result)

    def test_search_tokens_prefix_match(self):
        """Test search_tokens with prefix matching"""
        query_tokens = ["tes"]
        target_tokens = ["test", "file", "gcode"]
        result = search.search_tokens(query_tokens, target_tokens)
        self.assertTrue(result)

    def test_search_tokens_empty_query(self):
        """Test search_tokens with empty query"""
        query_tokens = []
        target_tokens = ["test", "file"]
        result = search.search_tokens(query_tokens, target_tokens)
        self.assertFalse(result)

    def test_search_tokens_empty_target(self):
        """Test search_tokens with empty target"""
        query_tokens = ["test"]
        target_tokens = []
        result = search.search_tokens(query_tokens, target_tokens)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
