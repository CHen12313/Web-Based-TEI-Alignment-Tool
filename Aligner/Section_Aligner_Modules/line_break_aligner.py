from bisect import bisect_right

from bs4 import Tag, Comment

from typing import List

from aligner_module_abc import AlignerModule
from data_classes import NON_PRINTED_TAGS, Element, AlignedPair

class LineBreakAligner(AlignerModule):
    """Aligns the elements (the <p>s) of one section.
    Anchors the source's <lb n> line numbers to the translation's <mls unit="Irish text line"> markers.
    """
    #Only works on pair 301042 so far, the other pairs have no <mls unit="Irish text line"> markers in the translation.
    def align(self, source_elements: List[Element], target_elements: List[Element],
              section_label: str | None = None) -> List[AlignedPair]:
        translation_start_lines: List[int] = []
        translation_paragraph_elements: List[Element] = []  #parallel to translation_start_lines: entry k = same paragraph
        output_list: List[AlignedPair] = []

        for paragraph in target_elements:
            irish_line_marker: Tag | None = paragraph.tag.find("mls", attrs={"unit": "Irish text line"})
            if irish_line_marker is None:
                continue
            translation_start_lines.append(int(irish_line_marker.get("n")))
            translation_paragraph_elements.append(paragraph)

        for position in range(1, len(translation_start_lines)):
            if translation_start_lines[position] < translation_start_lines[position - 1]:
                raise ValueError(f"mls line numbers out of order at line {translation_start_lines[position]}")

        for paragraph in source_elements:
            first_linebreak: Tag | None = paragraph.tag.find("lb")
            if first_linebreak is None or first_linebreak.get("n") is None:
                continue  # no numbered line inside this paragraph; TODO: handle

            if self._is_paragraph_start(first_linebreak, paragraph.tag):
                found_translation_element, starts_on_line = self._find_containing_translation_paragraph(
                    int(first_linebreak.get("n")), translation_start_lines, translation_paragraph_elements
                )
                if found_translation_element is None:
                    continue  # line comes before every translation start; TODO: handle (e.g. translation p1)
                if starts_on_line:
                    output_list.append(AlignedPair([paragraph], [found_translation_element], section_label))
                else:
                    pass
                    # TODO: starts_on_line False -> the Irish paragraph starts inside found_translation_element (merge)
            else:
                # TODO: paragraph does not start on its first lb -> start line has to be estimated
                pass
        return output_list

    def _is_paragraph_start(self, line_break: Tag, paragraph: Tag) -> bool:
        for element in line_break.previous_elements:
            if element is paragraph:
                return True #reached the start of the paragraph without hitting printed text

            if isinstance(element, Comment):
                if element.find_parent(list(NON_PRINTED_TAGS)) is not None:
                    continue #<note> is not printed in a file, so it doesn't count as the "start"
                if len(element.strip()) > 0:
                    return False
        raise ValueError(f"line_break <{line_break.name} n={line_break.get('n')}> is not inside the given paragraph")

    #Finds the translation paragraph whose range of Irish lines contains irish_start_line.
    #translation_start_lines: the Irish line each translation paragraph starts at (from its mls), ascending.
    #translation_paragraph_elements: the paragraph Element belonging to each entry of translation_start_lines.
    #Returns the paragraph Element (None if the line comes before every translation paragraph)
    # and whether that translation paragraph starts exactly on the line.
    def _find_containing_translation_paragraph(self, irish_start_line: int, translation_start_lines: List[int],
                                               translation_paragraph_elements: List[Element]) -> tuple[Element | None, bool]:
        insert_index: int = bisect_right(translation_start_lines, irish_start_line)
        containing_position: int = insert_index - 1

        if containing_position < 0:
            return None, False

        starts_exactly: bool = translation_start_lines[containing_position] == irish_start_line
        return translation_paragraph_elements[containing_position], starts_exactly
