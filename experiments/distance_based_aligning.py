from difflib import SequenceMatcher
#builds a table where each cell (i,j) holds the closest distance between 2 elements
#as it is in locate_mismatch, where it only uses the name of the tags, it will not work, the approach is to use LLM for semantic matching in <p> levels
# and distance based matching with SequenceMatcher to match on the section level. 
# The flow is then: match a section -> spawn a LLM aligner as a task (co-routine) that aligns on <p> -> if the 2 sections match, mark them as anchor for
# next section anchors are useful when finding out section-split mismatch

import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning, NavigableString, Comment, XMLParsedAsHTMLWarning
from bs4.element import ResultSet

from typing import List, Dict, Set, Tuple
from enum import StrEnum
from collections import Counter

import re
from bisect import bisect_left, bisect_right

from aligner import Element, AlignedPair, AnchorMethod
from utils import load_file_pair
from AlignmentRefiner import AlignmentRefiner, BoundaryShiftMerger

IGNORE_LIST: set[str] = { #<-AI wrote this set (list)
    "lb",   # line breaks of the printed edition: only marked in the Irish text
    "ex",   # expanded scribal abbreviations: only exist in the manuscript language
    "sup",  # words supplied by the editor/translator: naturally differ per language
    "pb",   # page breaks: source and translation printed on different pages
    "frn",  # foreign (Latin) words: marked in the source, not the translation
}

NON_COUNTED_ANCESTORS: set[str] = {"note", "rdg"}  # footnote text and variant readings are not part of the element's own content

def align_on_distance(original_elements: List[Element], translation_elements: List[Element], signature_tags: List[str] | None = None) -> list[AlignedPair]:
    #the sequence matcher matches by the name of the tags, which is not good, as they are all the same. We need to use the number of certain kinds of tags 
    # as names.
    signature_tags = ["lg", "l"] if signature_tags is None else signature_tags #default for the sake of testing and experimenting on 301043

    aligned_pairs = []

    original_tag_names: List[str] = []
    translation_tag_names: List[str] = []

    for original_div_element in original_elements:
        original_tag_names.append(make_counted_tag_name(original_div_element.tag, signature_tags))

    for translation_div_element in translation_elements:
        translation_tag_names.append(make_counted_tag_name(translation_div_element.tag, signature_tags))

    matcher: SequenceMatcher = SequenceMatcher(None, original_tag_names, translation_tag_names, autojunk=False)

    for operation, original_start, original_end, translation_start, translation_end in matcher.get_opcodes():
        #sequence matcher produces the paris in document order
        original_slice: List[Element] = original_elements[original_start:original_end]
        translation_slice: List[Element] = translation_elements[translation_start:translation_end]

        if operation == "equal":
            aligned_pairs += align_equal_pairs(original_slice, translation_slice)
        elif operation == "delete":
            aligned_pairs += align_delete_pairs(original_slice)
        elif operation == "insert":
            aligned_pairs += align_insert_pairs(translation_slice)
        elif operation == "replace":
            aligned_pairs += align_replace_pairs(original_slice, translation_slice)

    refiner_modules: List[AlignmentRefiner] = [
        BoundaryShiftMerger(max_matched_between=2)
    ]

    for module in refiner_modules:
        aligned_pairs = module.refine(aligned_pairs)

    return aligned_pairs

def align_equal_pairs(original_slice: List[Element], translation_slice: List[Element]) -> List[AlignedPair]:
    out_list: List[AlignedPair] = []
    for original, translation in zip(original_slice, translation_slice):
        out_list.append(AlignedPair([original], [translation], original.order_index, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE)) 
        #for now, we use the order index of the <p>s, later we need to pass in the section numbers 
        # the aligner is designed to be used to align sections, so we will be able to just extract it from the <div> elements or enumerate index

    return out_list

def align_delete_pairs(original_slice: List[Element]) -> List[AlignedPair]:
    out_list: List[AlignedPair] = []
    for original in original_slice:
        out_list.append(AlignedPair([original], [], original.order_index, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE))

    return out_list

def align_insert_pairs(translation_slice: List[Element]) -> List[AlignedPair]:
    out_list: List[AlignedPair] = []
    for translation in translation_slice:
        out_list.append(AlignedPair([], [translation], translation.order_index, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE))

    return out_list

def align_replace_pairs(original_slice: List[Element], translation_slice: List[Element]) -> List[AlignedPair]:
    out_list: List[AlignedPair] = []
    out_list.append(AlignedPair(original_slice, translation_slice, 
                                original_slice[0].order_index if original_slice else translation_slice[0].order_index, 
                                anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE))

    return out_list

def make_counted_tag_name(tag: Tag, signature_tags: List[str]) -> str:
        """
        takes a Tag, and produce a string of the format: \n
        `"<tag_name>|<descendant_tag_name_of_choice>:<occurrences>-..."` \n
        example: `"div0|lg:1-l:4"`
        """
        tag_counts: Counter[str] = Counter(descendant.name for descendant in tag.find_all(True) if descendant.find_parent(list(NON_COUNTED_ANCESTORS)) is None)
        #a descendent is only counted if it is not one of the unwanted ancestors
        tag_name = f"{tag.name}|" + "-".join([f"{child_tag}:{tag_counts[child_tag]}" for child_tag in signature_tags])
        return tag_name


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    original_tree, translation_tree = load_file_pair(file_code="301020B")
    original_body: Tag = original_tree.find("body")
    translation_body: Tag = translation_tree.find("body")

    section_numbers = ["5", "6", "7", "10", "12", "13", "19"]
    original_sections = [original_body.find("div0").find("div1", attrs={"n": n}, recursive=False) for n in section_numbers]
    translation_sections = [translation_body.find("div0").find("div1", attrs={"n": n}, recursive=False) for n in section_numbers]
    original_paragraphs = [Element(tag, index) for index, tag in enumerate(p for section in original_sections for p in section.find_all("p", recursive=False))]
    translation_paragraphs = [Element(tag, index) for index, tag in enumerate(p for section in translation_sections for p in section.find_all("p", recursive=False))]

    print(align_on_distance(original_paragraphs, translation_paragraphs, signature_tags=["lg", "l", "q"]))