import asyncio
from typing import List
from data_classes import AlignedPair, Element, DocumentSide, FixCommand, OPCode, CommandOutcome
import logging


logger = logging.getLogger(__name__)

class SuggestedFixApplier:
    def __init__(self, list_of_pairs: List[AlignedPair]):
        self.list_of_pairs = list_of_pairs
        self.element_pair_index_lookup: dict[str, int] = {}
        self._build_or_update_lookup()
            
    def apply_fix(self, command: FixCommand) -> CommandOutcome:
        try:
            if command.opcode == OPCode.SPLIT:
                return self._do_split(command.last_source_id_before_split, command.last_target_id_before_split)
                
            elif command.opcode == OPCode.MERGE:
                return self._do_merge(command.first_element_id, command.last_element_id)

            else: 
                logger.warning(f"⚠️ Unrecognized opcode: {command.opcode}")
                return CommandOutcome.REJECTED
        except KeyError as e:
            logger.exception(f"❌ invalid operand: {command.get_string(False)}")
        except Exception as e:
            logger.exception(f"❌ Unexpected exception: {e}")

    def _do_split(self, last_source_id_before_split: str, last_target_id_before_split: str) -> CommandOutcome:
        last_source_pair = self.list_of_pairs[self.element_pair_index_lookup[last_source_id_before_split]]
        last_target_pair = self.list_of_pairs[self.element_pair_index_lookup[last_target_id_before_split]]

        last_source_element_index = self._find_element_index_in_pair_linear(last_source_pair, last_source_id_before_split)
        last_target_element_index = self._find_element_index_in_pair_linear(last_target_pair, last_target_id_before_split)

        left_source_segment, right_source_segment = self._split_elements(last_source_pair.source_elements, last_source_element_index)
        left_target_segment, right_target_segment = self._split_elements(last_target_pair.target_elements, last_target_element_index)

        if last_source_pair == last_target_pair:
            left_new_pair = AlignedPair(left_source_segment, left_target_segment, last_source_pair.section_label)
            right_new_pair = AlignedPair(right_source_segment, right_target_segment, last_source_pair.section_label)
            pair_index = self.element_pair_index_lookup[last_source_id_before_split]
            self.list_of_pairs[pair_index : pair_index + 1] = [left_new_pair, right_new_pair]
            self._build_or_update_lookup()
            return CommandOutcome.APPLIED
        else:
            #if the 2 operands are in different AlignedPair objects, we cannot do it deterministically while keeping the ordering. 
            #example: pair1 = ([s1, s2 | s3, s4][t1, t2, t3, t4]) pair2 = ([s5, s6, s7, s8][t5, t6 | t7, t8]), | means split
            #we get pair1 = ([s1, s2][t1,t2,t3, t4]) pair2 = ([s5, s6, s7, s8][t5, t6]) new_pair = ([s3, s4][t7, t8])
            #but then we can't put them back into list_of_pairs, we either get: 
            # [s1, s2 | s3, s4 | s5, s6, s7, s8] [t1, t2, t3, t4 | t7, t8 | t5, t6] where the target elements doesn't line up
            #or we get: [s1, s2 | s5, s6, s7, s8 | s3, s4] [t1, t2, t3, t4 | t5, t6 | t7, t8] where the target doesn't lineup
            return CommandOutcome.REJECTED

    @staticmethod
    def _split_elements(elements: List[Element], last_index: int) -> tuple[List[Element], List[Element]]:
        """splits `elements` into everything up to and including `last_index`, and the rest"""
        return elements[:last_index + 1], elements[last_index + 1:]

    def _find_element_index_in_pair_linear(self, pair: AlignedPair, element_id: str) -> int:
        list_to_loop: List[Element] = pair.source_elements if element_id[0] == "S" else pair.target_elements

        for i, element in enumerate(list_to_loop):
            if str(element.order_index) == element_id[1]:
                return i

        return -1

    def _do_merge(self, first_element_id: str, last_element_id: str) -> CommandOutcome:
        """merges all the elements from `first_element_id` to `last_element_id` into one pair"""
        first_element_pair_index = self.element_pair_index_lookup[first_element_id]
        last_element_pair_index = self.element_pair_index_lookup[last_element_id]

        pairs_list_segment: List[AlignedPair] = self.list_of_pairs[first_element_pair_index : last_element_pair_index + 1]
        
        merged_pair = AlignedPair([], [])
        for pair in pairs_list_segment:
            merged_pair.source_elements += pair.source_elements
            merged_pair.target_elements += pair.target_elements

            merged_pair.section_label = pair.section_label if merged_pair.section_label is None else merged_pair.section_label

        self.list_of_pairs[first_element_pair_index : last_element_pair_index + 1] = [merged_pair]
        self._build_or_update_lookup() #rebuilding it is more computationally expensive than patching it, I do this to make the code simpler
        #at this scale the command should still run reasonably fast at O(N + n) where N is the number of pairs in self.list_of_pairs,
                                                                                    # and n is total amount of elements
        return CommandOutcome.APPLIED

    def _build_or_update_lookup(self) -> None:
        for index, pair in enumerate(self.list_of_pairs):
            for element in pair.source_elements:
                element_id = element.serialize(DocumentSide.SOURCE).get("id")
                self.element_pair_index_lookup[element_id] = index
            
            for element in pair.target_elements:
                element_id = element.serialize(DocumentSide.TARGET).get("id")
                self.element_pair_index_lookup[element_id] = index