from difflib import SequenceMatcher
#builds a table where each cell (i,j) holds the closest distance between 2 elements
#as it is in locate_mismatch, where it only uses the name of the tags, it will not work, the approach is to use LLM for semantic matching in <p> levels
# and distance based matching with SequenceMatcher to match on the section level.
# The flow is then: match a section -> spawn a LLM aligner as a task (co-routine) that aligns on <p> -> if the 2 sections match, mark them as anchor for
# next section anchors are useful when finding out section-split mismatch

import warnings

from bs4 import Tag, XMLParsedAsHTMLWarning

from typing import List
from collections import Counter

from aligner_module_abc import AlignerModule
from data_classes import Element, AlignedPair, AnchorMethod
from utils import load_file_pair
from alignment_refiner_abc import AlignmentRefiner
from Alignment_Refiner_Modules.boundary_shift_merger import BoundaryShiftMerger

IGNORE_LIST: set[str] = { #<-AI wrote this set (list)
    "lb",   # line breaks of the printed edition: only marked in the Irish text
    "ex",   # expanded scribal abbreviations: only exist in the manuscript language
    "sup",  # words supplied by the editor/translator: naturally differ per language
    "pb",   # page breaks: source and translation printed on different pages
    "frn",  # foreign (Latin) words: marked in the source, not the translation
}

NON_COUNTED_ANCESTORS: set[str] = {"note", "rdg"}  # footnote text and variant readings are not part of the element's own content

class DistanceBasedAligner(AlignerModule):
    """Aligns the elements (e.g. the `<p>`s) of one section. \n
    Compares the elements' structural tag counts with SequenceMatcher, then merges the orphans caused by shifted boundaries.
    """
    def __init__(self, signature_tags: List[str] | None = None, refiner_modules: List[AlignmentRefiner] | None = None):
        #the sequence matcher matches by the name of the tags, which is not good, as they are all the same. We need to use the number of certain kinds of tags
        # as names.
        self.signature_tags: List[str] = ["lg", "l"] if signature_tags is None else signature_tags #default for the sake of testing and experimenting on 301043
        self.refiner_modules: List[AlignmentRefiner] = [BoundaryShiftMerger(max_matched_between=2)] if refiner_modules is None else refiner_modules

    def align(self, source_elements: List[Element], target_elements: List[Element],
              section_label: str | None = None) -> List[AlignedPair]:
        aligned_pairs: List[AlignedPair] = []

        source_tag_names: List[str] = [self._make_counted_tag_name(element.tag) for element in source_elements]
        target_tag_names: List[str] = [self._make_counted_tag_name(element.tag) for element in target_elements]

        matcher: SequenceMatcher = SequenceMatcher(None, source_tag_names, target_tag_names, autojunk=False)

        for operation, source_start, source_end, target_start, target_end in matcher.get_opcodes():
            #sequence matcher produces the pairs in document order
            source_slice: List[Element] = source_elements[source_start:source_end]
            target_slice: List[Element] = target_elements[target_start:target_end]

            if operation == "equal":
                aligned_pairs += self._align_equal_pairs(source_slice, target_slice, section_label)
            elif operation == "delete":
                aligned_pairs += self._align_delete_pairs(source_slice, section_label)
            elif operation == "insert":
                aligned_pairs += self._align_insert_pairs(target_slice, section_label)
            elif operation == "replace":
                aligned_pairs += self._align_replace_pairs(source_slice, target_slice, section_label)

        for module in self.refiner_modules:
            aligned_pairs = module.refine(aligned_pairs)

        return aligned_pairs

    def _align_equal_pairs(self, source_slice: List[Element], target_slice: List[Element], section_label: str | None) -> List[AlignedPair]:
        out_list: List[AlignedPair] = []
        for source, target in zip(source_slice, target_slice):
            out_list.append(AlignedPair([source], [target], section_label, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE))

        return out_list

    def _align_delete_pairs(self, source_slice: List[Element], section_label: str | None) -> List[AlignedPair]:
        out_list: List[AlignedPair] = []
        for source in source_slice:
            out_list.append(AlignedPair([source], [], section_label, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE))

        return out_list

    def _align_insert_pairs(self, target_slice: List[Element], section_label: str | None) -> List[AlignedPair]:
        out_list: List[AlignedPair] = []
        for target in target_slice:
            out_list.append(AlignedPair([], [target], section_label, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE))

        return out_list

    def _align_replace_pairs(self, source_slice: List[Element], target_slice: List[Element], section_label: str | None) -> List[AlignedPair]:
        return [AlignedPair(source_slice, target_slice, section_label, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE)]

    def _make_counted_tag_name(self, tag: Tag) -> str:
        """
        takes a Tag, and produce a string of the format: \n
        `"<tag_name>|<descendant_tag_name_of_choice>:<occurrences>-..."` \n
        example: `"div0|lg:1-l:4"`
        """
        tag_counts: Counter[str] = Counter(descendant.name for descendant in tag.find_all(True) if descendant.find_parent(list(NON_COUNTED_ANCESTORS)) is None)
        #a descendent is only counted if it is not one of the unwanted ancestors
        return f"{tag.name}|" + "-".join([f"{child_tag}:{tag_counts[child_tag]}" for child_tag in self.signature_tags])


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

    print(DistanceBasedAligner(signature_tags=["lg", "l", "q"]).align(original_paragraphs, translation_paragraphs, "1"))
