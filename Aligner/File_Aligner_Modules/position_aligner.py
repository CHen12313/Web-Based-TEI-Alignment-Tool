from typing import List

from aligner_module_abc import AlignerModule
from data_classes import Element, AlignedPair

class PositionAligner(AlignerModule):
    """Aligns a file's sections (the <div>s) by their index on each side.
    Only valid when both sides have the same number of sections; raises ValueError otherwise.
    """
    def align(self, source_elements: List[Element], target_elements: List[Element],
              section_label: str | None = None) -> List[AlignedPair]:
        #section_label is not used, every pair is labelled with its index
        if len(source_elements) != len(target_elements):
            raise ValueError("source_elements and target_elements must have the same length")

        return [
            AlignedPair([source_element], [target_element], str(index))
            for index, (source_element, target_element) in enumerate(zip(source_elements, target_elements))
        ]
