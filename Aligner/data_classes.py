import re

from itertools import takewhile

from bs4 import Tag

from typing import List
from enum import StrEnum

NON_PRINTED_TAGS: set[str] = {
    "note",  # editorial footnotes, printed at the bottom of the page and not part of the running text
    "rdg",   # variant readings inside <app>, only the <lem> reading is printed in the text
}

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

class DocumentSide(StrEnum):
    SOURCE = "S"
    TARGET = "T"

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

    def get_clean_text(self, recursive: bool = True) -> str:
        content_pieces = self.tag.find_all(string = True, recursive=recursive)
        kept_pieces = [
            str(piece) for piece in content_pieces
            if not any(parent.name in NON_PRINTED_TAGS for parent in takewhile(lambda parent: parent is not self.tag, piece.parents))
            #the self.tag itself can be inside of an NON_PRINTED_TAGS, so we need to avoid checking the parent above the self.tag or else it could fail every test
            ]
        out_string = "".join(kept_pieces)
        return out_string


    def get_tag_string(self) -> str:
        """Stringify the tag attribute, for debug only. Whitespace runs (including the
        pretty-printed newlines/indentation from the source XML) are collapsed to a single
        space so the string stays on one line."""
        return re.sub(r"\s+", " ", str(self.tag)).strip()

    def serialize(self, side: DocumentSide, for_llm: bool = True) -> dict:
        """Serialize the element into a dict, so the LLM can process it better as a string. Not meant for sending to the frontend.

        Output schema:
        ```python
        {
            # tag name, e.g. "p" or "div1"
            "name": str,
            # full markup of the element, including its children
            "tag_string": str,
            # the element's n attribute, None if it has none
            "section_number": str | None
        }
        ```
        """
        return {
            "name" : self.name,
            "id" : str(side) + str(self.order_index), #S1, or T1, the LLM needs it to identify elements and issue fix commands
            "tag_string" : self.get_tag_string() if for_llm else self.get_clean_text(), #this is for the LLM, which needs the text of the tag
            #I need to find out which of raw string tag (with markup preserved) or the cleaned "pure" string works better
            "section_number" : self.section_number
        }

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

    def serialize(self, for_llm: bool = True) -> dict:
        """Serialize the pair into a dict, so the LLM can process it better as a string. Not meant for sending to the frontend.

        Output schema:
        ```python
        {
            # original (Irish) elements, in document order
            "source_elements": list[Element.serialize()],
            # translation (English) elements, in document order
            "target_elements": list[Element.serialize()],
            # div1@n of the section, None if the file has no numbers
            "section_label": str | None,
            # 0.0 (guess) to 1.0 (certain)
            "confidence_score": float | None,
            # an AnchorMethod value, e.g. "section_number"
            "anchor_method": str,
            # nested pairs one level down, empty at the lowest level
            "child_pairs": list[AlignedPair.serialize()]
        }
        ```
        """
        return {
            "source_elements" : [element.serialize(DocumentSide.SOURCE, for_llm) for element in self.source_elements],
            "target_elements" : [element.serialize(DocumentSide.TARGET, for_llm) for element in self.target_elements],
            "section_label" : self.section_label,
            "confidence_score" : self.confidence_score,
            "anchor_method" : self.anchor_method,
            "alignment_kind" : self.alignment_kind,
            "child_pairs" : [pair.serialize() for pair in self.child_pairs]
        }
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
