import asyncio
import json
import os
import warnings

from typing import List

from anthropic import AsyncAnthropic
from bs4 import XMLParsedAsHTMLWarning
from dotenv import load_dotenv

from aligner import AlignedPair, Element
from distance_based_aligning import align_on_distance
from prompt_templates import ALIGN_PROMPT_TEMPLATE, ALIGN_RESPONSE_SCHEMA

from utils import load_file_pair

load_dotenv()

MODEL = "claude-haiku-5-5"

async def verify_segment(start_index:int, end_index:int, pairs_list: List[AlignedPair], prompt_template: str, client: AsyncAnthropic) -> dict:
    end_index = min(end_index, len(pairs_list))
    formatted_prompt: str = prepare_prompt(pairs_list[start_index:end_index], prompt_template)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": ALIGN_RESPONSE_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": formatted_prompt,
        }]
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)

async def verify_aligned_pairs(aligned_pairs: List[AlignedPair], client: AsyncAnthropic | None, 
                               prompt_template: str = ALIGN_PROMPT_TEMPLATE, segment_size: int = 3) -> List[dict]:
    if not client:
        api_key = os.environ["ANTHROPIC_API_KEY"]
        client = AsyncAnthropic(api_key=api_key)

    verified_dicts = await asyncio.gather(
        *(verify_segment(i, i + segment_size, aligned_pairs, prompt_template, client) for i in range(0, len(aligned_pairs), segment_size))
    )

    return verified_dicts

def prepare_prompt(aligned_pairs: List[AlignedPair], prompt_template: str = ALIGN_PROMPT_TEMPLATE) -> str:
    serialized_pairs = [str(pair.serialize()) for pair in aligned_pairs]
    separator = "\n====================================================================================================\n\n"
    string_pairs = separator.join(serialized_pairs)
    formatted_prompt = prompt_template.format(string_pairs=string_pairs)
    return formatted_prompt



if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    original_tree, translation_tree = load_file_pair(file_code="301043")
    original_div0 = original_tree.find("body").find("div0")
    translation_div0 = translation_tree.find("body").find("div0")

    original_paragraphs = [Element(tag, index) for index, tag in enumerate(original_div0.find_all("p", recursive=False))]
    translation_paragraphs = [Element(tag, index) for index, tag in enumerate(translation_div0.find_all("p", recursive=False))]

    aligned_pairs = align_on_distance(original_paragraphs, translation_paragraphs, signature_tags=["lg", "l", "q"])

    print(prepare_prompt(aligned_pairs, "abc"))