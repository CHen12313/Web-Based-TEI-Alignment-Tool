from abc import ABC, abstractmethod
from typing import List

from data_classes import Element, AlignedPair

class AlignerModule(ABC):
    """Base class for every module that pairs the source elements with the target elements.

    The same contract covers section aligners (pair `<div>`s) and element aligners
    (pair `<p>`s or child `<div>`s), so `aligner.py` can swap them without caring which
    one it holds. Settings (e.g. `signature_tags`) belong in the subclass `__init__`, not in
    `align`, so that `align` has one signature that all subclasses share.
    """
    @abstractmethod
    def align(self, source_elements: List[Element], target_elements: List[Element],
              section_label: str | None = None) -> List[AlignedPair]:
        """Pair the elements of both sides and return the pairs in document order.

        An element with no counterpart must come back as an orphan (an `AlignedPair` with the
        other side empty) instead of being dropped, because a missing element is itself a finding.
        `section_label` is copied onto every pair for pairs that do not carry their own label.
        """
        ...
