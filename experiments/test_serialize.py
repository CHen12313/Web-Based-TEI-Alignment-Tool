import json
import sys
import warnings

from bs4 import XMLParsedAsHTMLWarning

from aligner import AlignedPair, AnchorMethod, Element
from utils import load_file_pair

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8") #the Windows console defaults to GBK, which can't print Irish characters like Ē
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    original_tree, translation_tree = load_file_pair(file_code="301043")
    original_paragraphs = original_tree.find("body").find_all("p")
    translation_paragraphs = translation_tree.find("body").find_all("p")

    pair = AlignedPair(
        [Element(original_paragraphs[0], 0)],
        [Element(translation_paragraphs[0], 0)],
        section_label="1",
        confidence_score=0.5,
        anchor_method=AnchorMethod.POSITION,
    )

    serialized = pair.serialize()
    print(serialized)
    print(json.dumps(serialized, ensure_ascii=False, indent=2))
