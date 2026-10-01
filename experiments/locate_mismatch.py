import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import ResultSet

from typing import List

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

original_tree = load_tei(SAMPLES_FOLDER/"G301020B.xml")
translation_tree = load_tei(SAMPLES_FOLDER/"T301020B.xml")

original_div1s: List[Tag] = original_tree.find_all("div1")
if original_div1s is None:
    print("No div1 in original tree")
    exit()

translation_div1s: List[Tag] = translation_tree.find_all("div1") #returns a list of all div1 elements 
if translation_div1s is None:
    print("No div1 in translation tree")
    exit()

counter = 1
section_mismatches = {}
for original_div1, translation_div1 in zip(original_div1s, translation_div1s):
    print(f"section {counter}:")
    mismatches = compare_occurrences(original_div1.find_all(True), translation_div1.find_all(True))
    if mismatches:
        section_mismatches[counter] = mismatches
    #the find_all(True) gives it all the nested elements inside the div1
    counter+=1
print(section_mismatches)