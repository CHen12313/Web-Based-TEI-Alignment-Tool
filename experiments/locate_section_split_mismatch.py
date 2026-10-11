import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import ResultSet

from typing import List

from collections import Counter

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

class element:
    """This class it meant to store information of each <p> elements. It CAN be used on other elements, but for the the experiment,
    we will be finding issues where the paragraphs are split different across files. And the advantage is that the boundaries are given,
    therefore we do not need a "locater" to find the end tag, which saves complexity. Also, for the alignment, we will be using length-based
    technique that measures the lengths of original and translation. A paragraph would have more characters, so that minor differences in char-count
    across languages would be less "dominant", which should hopefully improve matching accuracy.
    """
    def __init__(self, input_element: Tag):
        self.name = input_element.name
        self.length = input_element.__len__()
        self.source_line = input_element.sourceline
        self.source_column = input_element.sourceepos #the column that the element is located in source file
        self.section_number = input_element.get("n") #we get the section number for that element, not every file has that, so None if "none"
        self.order_index = None #this stores the position in document order among all other tags

class aligned_pair:
    def __init__(self):
        pass

def load_tei(file_path: str) -> BeautifulSoup:
    raw_text = Path(file_path).read_text(encoding="iso-8859-1")
    return BeautifulSoup(raw_text, "html.parser")

def get_comparable_children(parent_tag: Tag) -> list[Tag]:
    return [child for child in parent_tag.children if isinstance(child, Tag) and child.name not in IGNORE_LIST]

def align_elements(oroginal_tags: List[Tag], translation_tags: List[Tag]):
    pass




original_tree = load_tei(SAMPLES_FOLDER/"G301042B.xml")
translation_tree = load_tei(SAMPLES_FOLDER/"T301042B.xml")