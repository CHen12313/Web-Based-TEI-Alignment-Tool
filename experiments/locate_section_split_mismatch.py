import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning, NavigableString, Comment
from bs4.element import ResultSet

from typing import List, Dict, Set, Tuple

import re
from aligner import division_pattern

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SAMPLES_FOLDER = Path(__file__).resolve().parent.parent / "celt_samples"

IGNORE_LIST: set[str] = { #<-AI wrote this set (list)
    "lb",   # line breaks of the printed edition: only marked in the Irish text
    "ex",   # expanded scribal abbreviations: only exist in the manuscript language
    "sup",  # words supplied by the editor/translator: naturally differ per language
    "pb",   # page breaks: source and translation printed on different pages
    "frn",  # foreign (Latin) words: marked in the source, not the translation
}


#this script will work on 301042
#one key convention is that it aligns the translation ONTO the original

    
def load_tei(file_path: str) -> BeautifulSoup:
    raw_text = Path(file_path).read_text(encoding="iso-8859-1")
    return BeautifulSoup(raw_text, "html.parser")

def get_comparable_children(parent_tag: Tag) -> list[Tag]:
    return [child for child in parent_tag.children if isinstance(child, Tag) and child.name not in IGNORE_LIST]


original_tree = load_tei(SAMPLES_FOLDER/"G301042B.xml")
translation_tree = load_tei(SAMPLES_FOLDER/"T301042B.xml")

original_body = original_tree.find("body")
translation_body = translation_tree.find("body")



original_divs: ResultSet[Tag] = original_body.find_all(division_pattern, recursive=False)
#we use the regex pattern to find all kinds of divs, and do it non-recursively, because we need to preserve the structure, 
# recursive would flatten everything into a list.
if not original_divs:
    print("No div in original tree")
    exit()

translation_divs: ResultSet[Tag] = translation_body.find_all(division_pattern, recursive=False)
if not translation_divs:
    print("No div in translation tree")
    exit()