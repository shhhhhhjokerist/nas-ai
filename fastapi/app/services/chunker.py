"""Split parsed text into overlapping chunks for embedding."""

from langchain_text_splitters import RecursiveCharacterTextSplitter

# Separators ordered from coarsest to finest — the splitter tries each in turn.
# Chinese punctuation included so that sentence/paragraph boundaries are preferred.
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split *text* into overlapping chunks using recursive character splitting.

    Parameters
    ----------
    text : str
        The full document text to split.
    chunk_size : int
        Target chunk size in characters.
    chunk_overlap : int
        Number of characters to overlap between consecutive chunks.

    Returns
    -------
    list[str]
        Chunk strings (may be empty if *text* is empty).
    """
    if not text:
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_SEPARATORS,
        length_function=len,
        is_separator_regex=False,
    )
    return splitter.split_text(text)
