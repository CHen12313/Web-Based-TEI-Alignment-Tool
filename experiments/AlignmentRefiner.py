from abc import ABC, abstractmethod
from aligner import AnchorMethod, Element, AlignedPair
from bs4 import BeautifulSoup, Tag
from typing import List

class AlignmentRefiner(ABC):
    @abstractmethod
    def refine(self, aligned_pairs: List[AlignedPair]) -> List[AlignedPair]:
        """Take a list of aligned pairs and return a refined list."""
        ...

class BoundaryShiftMerger(AlignmentRefiner):
    """Merges orphans caused by a moved paragraph boundary into one many-to-many pair.

    When a boundary is placed differently in the two files, content moves into the
    neighbouring paragraph, so the matcher pairs one part and orphans the rest:

        source:  [p|lg:0-l:0-q:2]  [p|lg:0-l:0-q:0]
        target:  [p|lg:0-l:0-q:0]  [p|lg:0-l:0-q:2]

        matcher: target-only T1, (S1 <-> T2), source-only S2
        merged:  (S1, S2 <-> T1, T2)

    Orphans from both sides close together are far more likely one moved boundary
    than two separate omissions, so runs with orphans from both sides and at most
    `max_matched_between` matched pairs between them are merged. Merged pairs are a
    guess, to be validated later. Returns a new list.
    """
    def __init__(self, max_matched_between: int = 2):
        super().__init__()
        self.max_matched_between = max_matched_between

    def refine(self, aligned_pairs: List[AlignedPair]) -> List[AlignedPair]:
        left_index: int = 0
        refined_list = []

        while left_index < len(aligned_pairs) and left_index < len(aligned_pairs):
            left_pair: AlignedPair = aligned_pairs[left_index]
            if not self._is_orphan(left_pair):
                refined_list.append(left_pair)
                left_index += 1
                continue

            right_index: int = left_index + 1
            segment_end_index: int = left_index
            has_source_only = len(left_pair.target_elements) == 0 and len(left_pair.source_elements) != 0
            has_target_only = len(left_pair.source_elements) == 0 and len(left_pair.target_elements) != 0
            matched_since_last_orphan = 0

            while right_index < len(aligned_pairs):
                right_pair = aligned_pairs[right_index]
                if self._is_orphan(right_pair): 
                    segment_end_index = right_index
                    has_source_only = has_source_only or (len(right_pair.source_elements) != 0 and len(right_pair.target_elements) == 0)
                    has_target_only = has_target_only or (len(right_pair.target_elements) != 0 and len(right_pair.source_elements) == 0)
                    matched_since_last_orphan = 0
                else:
                    matched_since_last_orphan += 1
                    if matched_since_last_orphan > self.max_matched_between:
                        break

                right_index += 1

            segment: List[AlignedPair] = aligned_pairs[left_index: segment_end_index + 1]
            if has_source_only and has_target_only:
                refined_list += self._merge_segment(segment)
            else:
                refined_list += segment

            left_index = segment_end_index + 1
                        
        return refined_list

    def _is_orphan(self, aligned_pair: AlignedPair) -> bool:
        return (len(aligned_pair.source_elements) == 0) != (len(aligned_pair.target_elements) == 0) #xor

    def _merge_segment(self, aligned_pairs_segment: List[AlignedPair]) -> List[AlignedPair]:
        section_label = aligned_pairs_segment[0].section_label
        target_elements: List[Element] = []
        source_elements: List[Element] = []
        for pair in aligned_pairs_segment:
            if pair.source_elements:
                source_elements += pair.source_elements
            
            if pair.target_elements:
                target_elements += pair.target_elements

        return [AlignedPair(source_elements, target_elements, section_label, anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE)]