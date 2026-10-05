import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import ResultSet

from typing import List

from difflib import SequenceMatcher

from collections import Counter

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SAMPLES_FOLDER = Path(__file__).resolve().parent.parent / "celt_samples"

IGNORE_LIST: set[str] = { #<-AI wrote this set (list)
    "lb",   # line breaks of the printed edition: only marked in the Irish text
    "ex",   # expanded scribal abbreviations: only exist in the manuscript language
    "sup",  # words supplied by the editor/translator: naturally differ per language
    "pb",   # page breaks: source and translation printed on different pages
    "frn",  # foreign (Latin) words: marked in the source, not the translation
}

def load_tei(file_path: str) -> BeautifulSoup:
    raw_text = Path(file_path).read_text(encoding="iso-8859-1")
    return BeautifulSoup(raw_text, "html.parser")

def get_comparable_children(parent_tag: Tag) -> list[Tag]:
    return [child for child in parent_tag.children if isinstance(child, Tag) and child.name not in IGNORE_LIST]

def compare_occurrences(original_tags: List[Tag], translation_tags: List[Tag]) -> dict:
    #output format {<tag>: (<original_tag_occurrences>, <translation_tag_occurrences>)}
    original_tag_occurrences: Counter[str] = Counter(tag.name for tag in original_tags)
    translation_tag_occurrences: Counter[str] = Counter(tag.name for tag in translation_tags)

    tags_union: set[str] = set(original_tag_occurrences) | set(translation_tag_occurrences)

    mismatches = {}
    #compare the mismatches to try and 
    for tag in tags_union:
        tag_original_count = original_tag_occurrences.get(tag, 0)
        tag_translation_count = translation_tag_occurrences.get(tag, 0)
        if (tag_original_count != tag_translation_count) and (tag not in IGNORE_LIST):
            print(f"mismatch: {tag} | original: {original_tag_occurrences.get(tag, 0)} | translation: {translation_tag_occurrences.get(tag, 0)}")
            mismatches[tag] = (tag_original_count, tag_translation_count)

    return mismatches

def locate_mismatch(original_parent_tag: Tag, translation_parent_tag: Tag, name_only=False) -> dict:
    """the differences are output as original -> translation.
    name_only makes it so the function only returns tag names and not their content"""
    original_only: list[Tag] = []
    translation_only: list[Tag] = []

    original_tag_children = get_comparable_children(original_parent_tag)
    translation_tag_children = get_comparable_children(translation_parent_tag)

    def _find(original_tags: List[Tag], translation_tags: List[Tag]):
        if not original_tags and not translation_tags:
            #this is actually redundant, because with 2 empty lists the function would exit, but it's here for readability
            return
        
        original_names = [tag.name for tag in original_tags]
        translation_names = [tag.name for tag in translation_tags]
        matcher: SequenceMatcher = SequenceMatcher(None, original_names, translation_names, autojunk=False)
        equals: List[tuple[Tag, Tag]] = [] 
        #each call needs its own equals, other wise it would keep growing and we do a lot of repeated work

        for operation, o_start, o_end, t_start, t_end in matcher.get_opcodes(): #o for original, t for translation
            if operation == "equal":
                equals.extend(zip(original_tags[o_start:o_end], translation_tags[t_start:t_end]))
                continue
            original_only.extend(original_names[o_start:o_end] if name_only else original_tags[o_start:o_end])
            translation_only.extend(translation_names[t_start:t_end] if name_only else translation_tags[t_start:t_end])

        for original_tag, translation_tag in equals:
            _find(get_comparable_children(original_tag), get_comparable_children(translation_tag))

    _find(original_tag_children, translation_tag_children)

    return {
        "translation_only": translation_only,
        "original_only": original_only
    }

original_tree = load_tei(SAMPLES_FOLDER/"G301020B.xml")
translation_tree = load_tei(SAMPLES_FOLDER/"T301020B.xml")

original_div1s: ResultSet[Tag] = original_tree.find_all("div1")
if original_div1s is None:
    print("No div1 in original tree")
    exit()

translation_div1s: ResultSet[Tag] = translation_tree.find_all("div1") #returns a list of all div1 elements 
if translation_div1s is None:
    print("No div1 in translation tree")
    exit()

counter = 0
section_mismatches = {}
section_mismatches_locations = {}
for original_div1, translation_div1 in zip(original_div1s, translation_div1s):
    print(f"div {counter}:")

    original_section_number = original_div1.get("n")
    translation_section_number = translation_div1.get("n")
    if original_section_number != translation_section_number:
        print(f"Section number mismatch:\n  oroginal - {original_section_number}\n  translation - {translation_section_number}")
        continue #doesn't make much sense to compare sections that doesn't line up
    
    mismatches = compare_occurrences(original_div1.find_all(True), translation_div1.find_all(True)) 
    #the find_all(True) gives it all the nested elements inside the div1
    if mismatches:
        section_mismatches[original_section_number] = mismatches #doesn't matter which one we use, they are the same anyway

    #we check level by level
    mismatches_locations = locate_mismatch(original_div1, translation_div1, True) 
    #we don't want nested, so we don't do find_all(True)
    if mismatches_locations["original_only"] or mismatches_locations["translation_only"]:
        section_mismatches_locations[original_section_number] = mismatches_locations

    counter+=1
print(section_mismatches)
print(section_mismatches_locations)