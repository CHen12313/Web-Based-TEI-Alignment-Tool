from typing import Dict, List

from aligner_module_abc import AlignerModule
from data_classes import Element, AlignedPair, AnchorMethod

class SectionNumberAligner(AlignerModule):
    """Aligns a file's sections (the <div>s) that share the same n attribute.
    Needs unique numbers on both sides; a section whose number is on one side only becomes an orphan.
    """
    def align(self, source_elements: List[Element], target_elements: List[Element],
              section_label: str | None = None) -> List[AlignedPair]:
        #section_label is not used, every pair is labelled with its own div@n
        output_list: List[AlignedPair] = []
        source_number_lookup: Dict[str, Element] = self._build_number_lookup(source_elements)
        target_number_lookup: Dict[str, Element] = self._build_number_lookup(target_elements)

        for source_number, source_element in source_number_lookup.items():
            target_element: Element | None = target_number_lookup.get(source_number)
            #we use SECTION_NUMBER for orphans because they are still orphans produced by this AnchorMethod, design choice
            output_list.append(AlignedPair([source_element], [target_element] if target_element is not None else [], source_number, None, AnchorMethod.SECTION_NUMBER))

        #After the loop above, all <div> elements that are not added to the output_list would be orphans
        for target_number, target_element in target_number_lookup.items():
            if target_number not in source_number_lookup:
                output_list.append(AlignedPair([], [target_element], target_number, None, AnchorMethod.SECTION_NUMBER))

        return output_list

    def _build_number_lookup(self, elements: List[Element]) -> Dict[str, Element]:
        return {element.section_number: element for element in elements} #element.section_number is div.get("n"), a str
