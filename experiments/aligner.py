import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning, NavigableString, Comment
from bs4.element import ResultSet

from typing import List, Dict, Set, Tuple
from enum import StrEnum
from collections import Counter

import re
from bisect import bisect_left, bisect_right

NON_PRINTED_TAGS: set[str] = {"note"}

division_pattern: re.Pattern[str] = re.compile(r"^div\d?$") #this is to look for <div1>s and <div0>s

class AlignmentKind(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    SOURCE_ONLY = "source_only"
    TARGET_ONLY = "target_only"

class AnchorMethod(StrEnum): #AI wrote this class
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
        self.tag: Tag = input_element
        self.order_index: int = order_index
        self.start_line_number: int = start_line_number
        self.source_column: int = input_element.sourcepos #the column that the element is located in source file
        self.section_number: int | None = input_element.get("n") #we get the section number for that element, not every file has that, so None if "none"

    def __str__(self):
        return f"<{self.name}{' section=' + str(self.section_number) if self.section_number is not None else ''}{' order_index=' + str(self.order_index) if self.order_index is not None else ''}>"

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

    def __str__(self):
        source_string = "-".join([str(element) for element in self.source_elements])
        target_string = "-".join([str(element) for element in self.target_elements])

        return f"source_string: {source_string}\ntarget_string: {target_string}\nalignment_kind: {self.alignment_kind}" 

    def __repr__(self) -> str:
        source_string: str = ", ".join(str(element) for element in self.source_elements)
        target_string: str = ", ".join(str(element) for element in self.target_elements)

        return f"AlignedPair({self.alignment_kind}: source[{source_string}] -> target[{target_string}], anchor={self.anchor_method})"

def align_elements(original_tags: List[Tag], translation_tags: List[Tag]) -> Tuple[List[AlignedPair], List[AlignedPair]]:
    #entry point of the aligner
    aligned_sections: List[AlignedPair] = align_sections(original_tags, translation_tags)
    aligned_elements_per_section = []

    for sec in aligned_sections:
        if not sec.source_elements or not sec.target_elements:
            continue

        original_child_division_tags: List[Tag] = [
            child_division_tag 
            for division_element in sec.source_elements for child_division_tag in division_element.tag.find_all(division_pattern, recursive=False) 
        ]

        translation_child_division_tags: List[Tag] = [
            child_division_tag
            for division_element in sec.target_elements for child_division_tag in division_element.tag.find_all(division_pattern, recursive=False)
        ]

        if original_child_division_tags and translation_child_division_tags: 
            #we have to do recursion because there could be nested <div>s, without it, we only get the direct children of each section div
            sec.child_pairs = align_elements(original_child_division_tags, translation_child_division_tags)

        elif not original_child_division_tags and not translation_child_division_tags:
            original_paragraph_tags: List[Tag] = [
                paragraph_tag
                for division_element in sec.source_elements for paragraph_tag in division_element.tag.find_all("p", recursive=False)
            ]
            translation_paragraph_tags: List[Tag] = [
                paragraph_tag
                for division_element in sec.target_elements for paragraph_tag in division_element.tag.find_all("p", recursive=False)
            ]

            original_paragraph_elements: List[Element] = [
                Element(paragraph_tag, paragraph_index) for paragraph_index, paragraph_tag in enumerate(original_paragraph_tags)
            ]
            translation_paragraph_elements: List[Element] = [
                Element(paragraph_tag, paragraph_index) for paragraph_index, paragraph_tag in enumerate(translation_paragraph_tags)
            ]

            aligned_elements_per_section.append(align_individual_section(original_paragraph_elements, translation_paragraph_elements))

    return aligned_elements_per_section, aligned_sections

def align_sections(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> List[AlignedPair]:
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

    return align_as_one_block(original_tags, translation_tags)

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

def align_on_position(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> List[AlignedPair]:
    if len(original_tags) != len(translation_tags):
        raise ValueError("original_tags and translation_tags must have the same length")

    output_list: List[AlignedPair] = []

    for i, original_div in enumerate(original_tags):
        original_div_element = Element(original_div, i)
        translation_div_element = Element(translation_tags[i], i)

        output_list.append(AlignedPair([original_div_element], [translation_div_element])) 

    return output_list

def align_as_one_block(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> list[AlignedPair]:
    pass

#use a lookup table to store which <p n="x"> maps to which <p> in 
#For anchor, we use <lb> in Original and the <p n="x"> in translation
#For mapping, we take the <lb> from Original, and map it to the translation
#For one original <p> to multiple translation (one to many), we check the start of the translation paragraph(s), 
# if the corresponding line inside original is in the middle of a <p>, we know the original <p> was split into multiple translation <p>s
#For multiple original <p> being merged into one translation <p> (many to one), we check if the start of the original <p> falls in the middle of a 
# translation <p>, essentially the opposite of the one to many case
def align_individual_section(original_elements: List[Element], translation_elements: List[Element]) -> list[AlignedPair]:
    translation_start_lines: List[int] = []
    translation_paragraph_elements: List[Element] = []  #parallel to translation_start_lines: entry k = same paragraph
    output_list: List[AlignedPair] = []

    for paragraph in translation_elements:
        irish_line_marker: Tag | None = paragraph.tag.find("mls", attrs={"unit": "Irish text line"})
        if irish_line_marker is None:
            continue
        translation_start_lines.append(int(irish_line_marker.get("n")))
        translation_paragraph_elements.append(paragraph)

    for position in range(1, len(translation_start_lines)):
        if translation_start_lines[position] < translation_start_lines[position - 1]:
            raise ValueError(f"mls line numbers out of order at line {translation_start_lines[position]}")

    for paragraph in original_elements:
        first_linebreak: Tag | None = paragraph.tag.find("lb")
        if first_linebreak is None or first_linebreak.get("n") is None:
            continue  # no numbered line inside this paragraph; TODO: handle

        if is_paragraph_start(first_linebreak, paragraph.tag):
            found_translation_element, starts_on_line = find_containing_translation_paragraph(
                int(first_linebreak.get("n")), translation_start_lines, translation_paragraph_elements
            )
            if found_translation_element is None:
                continue  # line comes before every translation start; TODO: handle (e.g. translation p1)
            if starts_on_line:
                output_list.append(AlignedPair([paragraph], [found_translation_element]))
            else:
                pass
                # TODO: starts_on_line False -> the Irish paragraph starts inside found_translation_element (merge)
        else:
            # TODO: paragraph does not start on its first lb -> start line has to be estimated
            pass
    return output_list

def is_paragraph_start(line_break: Tag, paragraph: Tag):
    for element in line_break.previous_elements:
        if element is paragraph:
            return True #reached the start of the paragraph without hitting printed text
        
        if isinstance(element, Comment):
            if element.find_parent(list(NON_PRINTED_TAGS)) is not None:
                continue #<note> is not printed in a file, so it doesn't count as the "start"
            if len(element.strip()) > 0:
                return False
    raise ValueError(f"line_break <{line_break.name} n={line_break.get('n')}> is not inside the given paragraph")

def find_containing_translation_paragraph(irish_start_line: int, translation_start_lines: list[int],
                                            translation_paragraph_elements: list[Element]) -> tuple[Element | None, bool]:
    """Find the translation paragraph whose range of Irish lines contains irish_start_line.

    translation_start_lines: the Irish line each translation paragraph starts at (from its mls), ascending.
    translation_paragraph_elements: the paragraph Element belonging to each entry of translation_start_lines.
    Returns the paragraph Element (None if the line comes before every translation paragraph)
    and whether that translation paragraph starts exactly on the line.
    """
    insert_index: int = bisect_right(translation_start_lines, irish_start_line)
    containing_position: int = insert_index - 1

    if containing_position < 0:
        return None, False

    starts_exactly: bool = translation_start_lines[containing_position] == irish_start_line
    return translation_paragraph_elements[containing_position], starts_exactly
