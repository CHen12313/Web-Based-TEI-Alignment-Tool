import warnings
from pathlib import Path

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning
from bs4.element import ResultSet

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

SAMPLES_FOLDER = Path(__file__).resolve().parent.parent / "celt_samples"

def load_tei(file_path):
    """Read a CELT file and parse it into a tree"""
    raw_text = Path(file_path).read_text(encoding="iso-8859-1") #same encoding as original xml files
    return BeautifulSoup(raw_text, "html.parser")

def print_outline(element: Tag, max_depth: int = 3, depth: int = 0):
    """Recursively print the element tree, indented, and show tags and attributes"""
    if depth > max_depth:
        return 
    attributes: str = " ".join(f'{name} = "{value}"' for name, value in element.attrs.items())
    #Tag means one element from the xml file
    print(("    " * depth) + f"<{element.name} {attributes}>".replace(" >", ">"))
    for child in element.children:
        if isinstance(child, Tag):
            print_outline(child, max_depth, depth+1)

if __name__ == "__main__":
    soup: BeautifulSoup = load_tei(SAMPLES_FOLDER/"G301020B.xml")

    root: Tag | None = soup.find("tei.2") #tei.2 is the tag for the root element
    if root is None:
        raise ValueError("No root element found: the file may not have parsed")
    print(f"Root: {root.name} | id = {root.get("id")}")

    title: Tag | None = soup.find("title", attrs={"type" : "uniform"})
    if title is not None:
        print(f"Title: {title.get_text(strip=True)}")

    body: Tag | None = soup.find("body")
    if body is not None:
        max_depth = 2
        print(f"\n--- Body outline (depth {max_depth}) ---")
        print_outline(body, max_depth)

    print(f"\n--- Sections ---")
    sections: ResultSet[Tag] = soup.find_all("div1")
    for section in sections:
        section_number: str = section.get("n")
        paragraph_count: int = len(section.find_all("p"))
        line_count: int = len(section.find_all("l")) #all <l>
        print(f"Section {section_number} : {paragraph_count} paragraphs, {line_count} verse lines")

    first_line : Tag | None = soup.find("l")
    if first_line is not None:
        parent_section: Tag | None = first_line.find_parent("div1")
        print(f"\nFirst verse line: {first_line.get_text()}")
        print(f"Its parent: {first_line.parent.name if first_line.parent else None}")
        print(f"Its section: {parent_section.get("n") if parent_section else None}")