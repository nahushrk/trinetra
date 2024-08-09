from unittest import TestCase

from trinetra import search


class Test(TestCase):
    def test_tokenize(self):
        text = "Braided_Grass_Vases/files-2024!@#$%^&*()"
        tokens = search.tokenize(text)
        print(tokens)
