import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import ResultSet

from collections import Counter

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SAMPLES_FOLDER = Path(__file__).resolve().parent.parent / "celt_samples"

def load_tei(file_path: str) -> BeautifulSoup:
    raw_text = Path(file_path).read_text(encoding="iso-8859-1")
    return BeautifulSoup(raw_text, "html.parser")

original_tree = load_tei(SAMPLES_FOLDER/"G301020B.xml")
translation_tree = load_tei(SAMPLES_FOLDER/"T301020B.xml")

original_body: Tag = original_tree.find("body")
if original_body is None:
    print("No body in original tree")
    exit()

translation_body: Tag = translation_tree.find("body")
if translation_body is None:
    print("No body in translation tree")
    exit()


original_all_tags = original_body.find_all(True)
# original_tag_occurrences = {}
# for tag in original_all_tags:
#     if tag in original_tag_occurrences:
#         original_tag_occurrences[tag.name] += 1
#     original_tag_occurrences[tag.name] = 1

translation_all_tags = translation_body.find_all(True)
# translation_tag_occurrences = {}
# for tag in translation_all_tags:
#     if tag in translation_tag_occurrences:
#         translation_tag_occurrences[tag.name] += 1
#     translation_tag_occurrences[tag.name] = 1

#better to use counter, it does the same thing
original_tag_occurrences: Counter[str] = Counter(tag.name for tag in original_all_tags)
translation_tag_occurrences: Counter[str] = Counter(tag.name for tag in translation_all_tags)

tag_occurrences_union: set[str] = set(original_tag_occurrences) | set(translation_tag_occurrences) #merge the 2 occurrences
for tag in tag_occurrences_union:
    print(f"{tag:<12}{original_tag_occurrences.get(tag, 0):<5}{translation_tag_occurrences.get(tag, 0):<5}")

