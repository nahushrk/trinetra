import re


def tokenize(text) -> [str]:
    split_text = re.split(r"\W+|_", text)
    split_text = [word.lower() for word in split_text if word]
    return split_text


def search_tokens_all_match(query_tokens: [str], target_tokens: [str]) -> bool:
    return all(token in target_tokens for token in query_tokens)


def search_tokens(query_tokens: [str], target_tokens: [str]) -> bool:
    for query in query_tokens:
        if any(query == target or target.startswith(query) for target in target_tokens):
            return True
    return False
