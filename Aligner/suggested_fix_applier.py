import asyncio
from typing import List
from data_classes import AlignedPair, Element, DocumentSide

class SuggestedFixApplier:
    def __init__(self, list_of_pairs: List[AlignedPair]):
        self.list_of_pairs = list_of_pairs
        self.element_pair_index_lookup: dict[str, int] = {}

        for index, pair in enumerate(list_of_pairs):
            for element in pair.source_elements:
                element_id = element.serialize(DocumentSide.SOURCE).get("id")
                self.element_pair_index_lookup[element_id] = index
            
            for element in pair.target_elements:
                element_id = element.serialize(DocumentSide.TARGET).get("id")
                self.element_pair_index_lookup[element_id] = index
            
    def apply_fix(self, command: str):
        pass

    def _do_split(first_element_id: str, last_element_id: str):
        pass

    def _do_merge(last_source_id_before_split: str, last_target_id_before_split: str):
        pass

