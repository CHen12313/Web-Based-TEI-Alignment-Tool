from typing import List

from aligner_module_abc import AlignerModule
from data_classes import Element, AlignedPair

class OneBlockAligner(AlignerModule):
    """Aligns a file's sections as one single block, for files whose sections can't be matched by number or position.
    Not implemented yet, there is no reliable way to split the sections, so it raises instead of guessing.
    """
    def align(self, source_elements: List[Element], target_elements: List[Element],
              section_label: str | None = None) -> List[AlignedPair]:
        raise NotImplementedError("OneBlockAligner is not implemented yet")
