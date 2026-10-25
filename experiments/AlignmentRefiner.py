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
    def refine(self, aligned_pairs: List[AlignedPair]) -> List[AlignedPair]:
        for i, pair in enumerate(aligned_pairs):
