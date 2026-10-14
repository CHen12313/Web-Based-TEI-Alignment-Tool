import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import ResultSet

from typing import List, Dict, Set
from enum import StrEnum
from collections import Counter

import re

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
class AlignmentKind(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    SOURCE_ONLY = "source_only"
    TARGET_ONLY = "target_only"

class AnchorMethod(StrEnum):
    SECTION_NUMBER = "section_number"            # div1@n matches on both sides
    ELEMENT_ID = "element_id"                    # matching id attributes
    STRUCTURAL_SEQUENCE = "structural_sequence"  # tag-name sequence comparison (difflib)
    TEXT_LENGTH = "text_length"                  # length-ratio alignment with markup bonus
    POSITION = "position"                        # same index on both sides; last resort

class Element:
    """This class it meant to store information of each <p> elements. It CAN be used on other elements, but for the the experiment,
    we will be finding issues where the paragraphs are split different across files. And the advantage is that the boundaries are given,
    therefore we do not need a "locater" to find the end tag, which saves complexity. Also, for the alignment, we will be using length-based
    technique that measures the lengths of original and translation. A paragraph would have more characters, so that minor differences in char-count
    across languages would be less "dominant", which should hopefully improve matching accuracy.
    """
    def __init__(self, input_element: Tag, order_index: int = None, start_line_number: int = None):
        self.name: str = input_element.name
        self.start_line_number: int = None
        self.source_column: int = input_element.sourcepos #the column that the element is located in source file
        self.section_number: int | None = input_element.get("n") #we get the section number for that element, not every file has that, so None if "none"
        self.order_index: int = None #this stores the position in document order among all other tags, has to be assigned

class AlignedPair: #I worked out the attributes with claude, I asked it to do the comments so I don't forget
    def __init__(self, source_elements: List[Element], target_elements: List[Element],
                 section_label: str | None = None, confidence_score: float = 0.0, 
                 anchor_method: AnchorMethod = AnchorMethod.POSITION):
        # the original (Irish) elements in this pair, in document order;
        # one element normally, several for a merge, empty when the translation has no counterpart
        self.source_elements: List[Element] = source_elements

        # the translation (English) elements in this pair, in document order;
        # one element normally, several for a split, empty when the original has no counterpart
        self.target_elements: List[Element] = target_elements

        # the section number written in the file (div1@n), for showing to the user;
        # None when the file has no numbers (e.g. 301042's div0)
        self.section_label: str = section_label

        # how sure the aligner is that these elements correspond, from 0.0 (guess) to 1.0 (certain)
        self.confidence_score: float = confidence_score

        # which method produced this pairing (section number, position, length, ...),
        # so scanners know how far to trust it
        self.anchor_method: AnchorMethod = anchor_method

        # the alignment of the elements one level down, inside this pair
        # (e.g. the paragraph pairs inside a section pair);
        # empty until the aligner steps in, and stays empty at the lowest level
        self.child_pairs: list[AlignedPair] = []

    @property
    def alignment_kind(self) -> str:
        source_count: int = len(self.source_elements)
        target_count: int = len(self.target_elements)
        if source_count == 0:
            return AlignmentKind.TARGET_ONLY
        elif target_count == 0:
            return AlignmentKind.SOURCE_ONLY
        elif source_count == 1 and target_count == 1:
            return AlignmentKind.ONE_TO_ONE
        elif source_count == 1 and target_count > 1:
            return AlignmentKind.ONE_TO_MANY
        elif source_count > 1 and target_count == 1:
            return AlignmentKind.MANY_TO_ONE
        return AlignmentKind.MANY_TO_MANY


    
def load_tei(file_path: str) -> BeautifulSoup:
    raw_text = Path(file_path).read_text(encoding="iso-8859-1")
    return BeautifulSoup(raw_text, "html.parser")

def get_comparable_children(parent_tag: Tag) -> list[Tag]:
    return [child for child in parent_tag.children if isinstance(child, Tag) and child.name not in IGNORE_LIST]

def align_elements(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]):
    all_sections_numbered = True
    same_sections_count = True

    for div in [*original_tags, *translation_tags]:
        if div.get("n") is None:
            all_sections_numbered = False
            break

    same_sections_count = len(original_tags) == len(translation_tags)

    if all_sections_numbered:
        original_div_numbers = [div.get("n") for div in original_tags]
        translation_div_numbers = [div.get("n") for div in translation_tags]
        unique_original_div_numbers = len(set(original_div_numbers)) == len(original_div_numbers)
        unique_translation_div_numbers = len(set(translation_div_numbers)) == len(translation_div_numbers)
        if unique_original_div_numbers and unique_translation_div_numbers:
            return align_on_section_numbers(original_tags, translation_tags)

    if same_sections_count:
        return align_on_position(original_tags, translation_tags)

    return align_as_one_block()

    #use a lookup table to store which <p n="x"> maps to which <p> in 
    #For anchor, we use <lb> in Original and the <p n="x"> in translation
    #For mapping, we take the <lb> from Original, and map it to the translation
    #For one original <p> to multiple translation (one to many), we check the start of the translation paragraph(s), 
    # if the corresponding line inside original is in the middle of a <p>, we know the original <p> was split into multiple translation <p>s
    #For multiple original <p> being merged into one translation <p> (many to one), we check if the start of the original <p> falls in the middle of a 
    # translation <p>, essentially the opposite of the one to many case

def align_on_section_numbers(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> list[AlignedPair]:
    output_list: List[AlignedPair] = []
    original_div_number_lookup: Dict[str, Element] = {} #div.get("n") returns str
    translation_div_number_lookup: Dict[str, Element] = {}
    included_section_numbers: Set[str] = set()

    for i, original_div in enumerate(original_tags): 
        original_div_element = Element(original_div, i)
        original_div_number_lookup[original_div.get("n")] = original_div_element

    for i, translation_div in enumerate(translation_tags):
        translation_div_element = Element(translation_div, i)
        translation_div_number_lookup[translation_div.get("n")] = translation_div_element
        
    for original_div in original_tags:
        original_div_element = original_div_number_lookup[original_div.get("n")]

        if original_div.get("n") not in translation_div_number_lookup:
            output_list.append(AlignedPair([original_div_element], [], original_div.get("n"), None, AnchorMethod.SECTION_NUMBER))
            #we use SECTION_NUMBER for orphans because they are still orphans produced by this AnchorMethod, design choice
            included_section_numbers.add(original_div.get("n"))

        else:
            found_translation_div_element = translation_div_number_lookup[original_div.get("n")]
            output_list.append(AlignedPair([original_div_element], [found_translation_div_element], original_div.get("n"), None, AnchorMethod.SECTION_NUMBER))

            included_section_numbers.add(original_div.get("n"))

    #After this loop, all <div> elements that is not added to the output_list would be orphans 
    for translation_div in translation_tags:
        if translation_div.get("n") not in included_section_numbers:
            translation_div_element = translation_div_number_lookup[translation_div.get("n")]
            output_list.append(AlignedPair([], [translation_div_element], translation_div.get("n"), None, AnchorMethod.SECTION_NUMBER))

    return output_list

def align_on_position(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> list[AlignedPair]:
    pass

def align_as_one_block(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> list[AlignedPair]:
    pass

def align_section(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> list[AlignedPair]:
    original_elements: List[Element] = []
    translation_tags: List[Element] = []
    
    for i, tag in enumerate(original_tags):
        element = Element(tag, i)
        

original_tree = load_tei(SAMPLES_FOLDER/"G301042B.xml")
translation_tree = load_tei(SAMPLES_FOLDER/"T301042B.xml")

original_body = original_tree.find("body")
translation_body = translation_tree.find("body")

division_pattern: re.Pattern[str] = re.compile(r"^div\d?$") #this is to look for <div1>s and <div0>s

original_div0s: ResultSet[Tag] = original_body.find_all(division_pattern, recursive=False)
#we use the regex pattern to find all kinds of divs, and do it non-recursively, because we need to preserve the structure, 
# recursive would flatten everything into a list.
if not original_div0s:
    print("No div in original tree")
    exit()

translation_div0s: ResultSet[Tag] = translation_body.find_all(division_pattern, recursive=False)
if not translation_div0s:
    print("No div in translation tree")
    exit()