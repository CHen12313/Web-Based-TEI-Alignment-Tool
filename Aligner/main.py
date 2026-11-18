import asyncio
import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning, NavigableString
from bs4.element import ResultSet

from typing import List, Dict, Set, Tuple
from collections import Counter

import re
import logging

from data_classes import AnchorMethod, Element, AlignedPair, FixCommand, CommandOutcome

from Section_Aligner_Modules.distance_based_aligner import DistanceBasedAligner

from File_Aligner_Modules.section_number_aligner import SectionNumberAligner
from File_Aligner_Modules.position_aligner import PositionAligner
from File_Aligner_Modules.one_block_aligner import OneBlockAligner

from llm_based_verifier import verify_aligned_pairs
from suggested_fix_applier import SuggestedFixApplier

from Utils.setup_loggin import setup_logging #only resolves because llm_based_verifier adds the repo root to sys.path on import

from utils import load_file_pair

logger = logging.getLogger(__name__)

division_pattern: re.Pattern[str] = re.compile(r"^div\d?$") #this is to look for <div1>s and <div0>s

async def align_files(original_tags: List[Tag], translation_tags: List[Tag]) -> Tuple[List[AlignedPair], List[AlignedPair]]:
    logger.info("Aligning Sections...")
    aligned_sections = align_sections(original_tags, translation_tags)
    logger.info(f"✅ Aligned {len(aligned_sections)} sections")
    counter = [0,0]
    aligned_elements: List[AlignedPair] = []
    logger.info("Aligning elements...")
    for section in aligned_sections:
        align_individual_section(section, counter, aligned_elements)

    suggested_fix_commands: List[FixCommand] = await verify_aligned_pairs(aligned_elements, segment_size=8)
    total_commands = len(suggested_fix_commands)
    logger.info("🏁 Start applying fix commands...")
    applier_object = SuggestedFixApplier(aligned_elements)
    for command in suggested_fix_commands:
        outcome = applier_object.apply_fix(command)
        if outcome == CommandOutcome.REJECTED:
            logger.warning(f"⚠️ Command: {command} rejected")

    logger.info(f"✅ Finished applying commands. Applied: {applier_object.applied_command_count}/{total_commands} \
                | Errored: {applier_object.errored_command_count}/{total_commands} \
                    | Rejected: {applier_object.rejected_command_count}/{total_commands}")
    aligned_elements = applier_object.list_of_pairs
    return aligned_elements, aligned_sections


def align_individual_section(section: AlignedPair, counters: List[int], aligned_elements: List[AlignedPair]) -> None:
    if not section.source_elements or not section.target_elements:
        return

    section_label = section.section_label

    original_child_division_tags: List[Tag] = [
        child_division_tag 
        for division_element in section.source_elements for child_division_tag in division_element.tag.find_all(division_pattern, recursive=False) 
    ]

    translation_child_division_tags: List[Tag] = [
        child_division_tag
        for division_element in section.target_elements for child_division_tag in division_element.tag.find_all(division_pattern, recursive=False)
    ]

    if original_child_division_tags and translation_child_division_tags: 
        #we have to do recursion because there could be nested <div>s, without it, we only get the direct children of each section div
        original_child_division_elements: List[Element] = [
            Element(division_tag, counters[0] + division_index) for division_index, division_tag in enumerate(original_child_division_tags)
        ]
        translation_child_division_elements: List[Element] = [
            Element(division_tag, counters[1] + division_index) for division_index, division_tag in enumerate(translation_child_division_tags)
        ]

        counters[0] += len(original_child_division_elements)
        counters[1] += len(translation_child_division_elements)

        logger.info(f"Aligning section: {section_label}...")
        section.child_pairs = DistanceBasedAligner().align(original_child_division_elements, translation_child_division_elements, section_label)
        logger.info(f"Aligned section {section_label}")
        for child_pair in section.child_pairs:
            logger.info("↻ Recursing...")
            align_individual_section(child_pair, counters, aligned_elements)

    elif not original_child_division_tags and not translation_child_division_tags:
        original_paragraph_tags: List[Tag] = [
            paragraph_tag
            for division_element in section.source_elements for paragraph_tag in division_element.tag.find_all("p", recursive=False)
        ]
        translation_paragraph_tags: List[Tag] = [
            paragraph_tag
            for division_element in section.target_elements for paragraph_tag in division_element.tag.find_all("p", recursive=False)
        ]

        original_paragraph_elements: List[Element] = [
            Element(paragraph_tag, counters[0] + paragraph_index) for paragraph_index, paragraph_tag in enumerate(original_paragraph_tags)
        ]
        translation_paragraph_elements: List[Element] = [
            Element(paragraph_tag, counters[1] + paragraph_index) for paragraph_index, paragraph_tag in enumerate(translation_paragraph_tags)
        ]

        logger.info(f"Aligning section {section_label}...")
        aligned_elements.extend(DistanceBasedAligner(signature_tags=["lg", "l", "q"]).align(original_paragraph_elements, translation_paragraph_elements, section_label))
        logger.info(f"Aligned section {section_label}")
        counters[0] += len(original_paragraph_elements)
        counters[1] += len(translation_paragraph_elements)

def align_sections(original_tags: ResultSet[Tag], translation_tags: ResultSet[Tag]) -> List[AlignedPair]:
    original_elements: List[Element] = [Element(div, index) for index, div in enumerate(original_tags)]
    translation_elements: List[Element] = [Element(div, index) for index, div in enumerate(translation_tags)]
    all_sections_numbered = True
    same_sections_count = True

    for div in [*original_tags, *translation_tags]:
        if div.get("n") is None:
            all_sections_numbered = False
            break

    same_sections_count = len(original_tags) == len(translation_tags)

    if all_sections_numbered:
        original_div_numbers = [div.get("n") for div in original_tags]
        translation_div_numbers = [div.get("n") for div in translation_tags]
        unique_original_div_numbers = len(set(original_div_numbers)) == len(original_div_numbers)
        unique_translation_div_numbers = len(set(translation_div_numbers)) == len(translation_div_numbers)
        if unique_original_div_numbers and unique_translation_div_numbers:
            return SectionNumberAligner().align(original_elements, translation_elements)

    if same_sections_count:
        return PositionAligner().align(original_elements, translation_elements)

    return OneBlockAligner().align(original_elements, translation_elements)


if __name__ == "__main__":
    setup_logging()
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    original_tree, translation_tree = load_file_pair("301020B")
    original_body = original_tree.find("body")
    translation_body = translation_tree.find("body")
    
    original_sections = original_body.find("div0").find_all("div1", recursive=False)
    translation_sections = translation_body.find("div0").find_all("div1", recursive=False)

    print(f"{len(original_sections)} | {len(translation_sections)}")

    print(asyncio.run(align_files(original_sections, translation_sections)))