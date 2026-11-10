import asyncio
import json
import os
import sys
import warnings
import logging
from random import uniform

from pathlib import Path
from typing import List

from anthropic import AsyncAnthropic, APIError
from bs4 import XMLParsedAsHTMLWarning
from dotenv import load_dotenv

#had to do it for the imports to resolve
sys.path.append(str(Path(__file__).resolve().parent.parent))

from data_classes import AlignedPair, Element, DocumentSide
from distance_based_aligning import align_on_distance
from prompt_templates import ALIGN_PROMPT_TEMPLATE, ALIGN_RESPONSE_SCHEMA

from utils import load_file_pair
from Utils.util import load_file_content, save_to_file, save_dict_to_json, read_from_json
from Utils.setup_loggin import setup_logging


load_dotenv()
logger = logging.getLogger(__name__)
MODEL = "claude-haiku-5-5"

async def verify_segment(start_index:int, end_index:int, pairs_list: List[AlignedPair], 
                         prompt_template: str, client: AsyncAnthropic, max_retry: int = 2, base_delay: float = 1.0) -> dict | None:
    end_index = min(end_index, len(pairs_list))
    logger.info(f"Preparing prompt for segment: {start_index} - {end_index}...")
    formatted_prompt: str = prepare_prompt(pairs_list[start_index:end_index], prompt_template)
    logger.info(f"🟢 Prompt prepared for segment: {start_index} - {end_index}")

    logger.info(f"Issuing API call for segment: {start_index} - {end_index}...")
    for attempt in range(max_retry + 1):
        if attempt != 0: logger.info(f"⚠️ Retry [{attempt}/{max_retry}] for segment: {start_index} - {end_index}...") 
        try:
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
            text = json.loads(text)
            logger.info(f"🟢 Got response for segment : {start_index} - {end_index}")

            return text 
        
        except json.JSONDecodeError as e:
            logger.warning(f"🔴 JSON Decode Error while attempting to parse response for segment: {start_index} - {end_index}.")
            #could be LLM goofing with the schema, so an immediate retry to have it produce a hopefully good response
            if attempt == max_retry:
                logger.error(f"❌ Segment {start_index}-{end_index} failed after {max_retry} attempts: {e}")
                return None

        except APIError as e:
            logger.warning(f"🔴 API Error while attempting to verify segment: {start_index} - {end_index}.")
            delay = base_delay * (2 ** (attempt - 1) + uniform(0, 0.5))
            if attempt == max_retry:
                logger.error(f"❌ Segment {start_index}-{end_index} failed after {max_retry} attempts: {e}")
                return None
            #back off for some time and try again later, the more it tails, the longer to wait, wait time grows in power of 2 of attempts
            await asyncio.sleep(delay) 

async def verify_aligned_pairs(aligned_pairs: List[AlignedPair], client: AsyncAnthropic | None = None, 
                               prompt_template: str = ALIGN_PROMPT_TEMPLATE, segment_size: int = 3) -> List[dict]:
    if not client:
        api_key = os.environ["ANTHROPIC_API_KEY"]
        client = AsyncAnthropic(api_key=api_key)

    logger.info(f"🏁 Start verifying {len(aligned_pairs)} pairs with LLM...")
    verified_dicts = await asyncio.gather(
        *(verify_segment(i, i + segment_size, aligned_pairs, prompt_template, client) for i in range(0, len(aligned_pairs), segment_size))
    )
    logger.info(f"✅ Verification complete. Succeeded Segments: {len(verified_dicts)} | Total Segments: {-(-len(aligned_pairs) // segment_size)}")
    #this is to round UP to the nearest integer, floor division rounds towards negative inf, so flip it to negative for the division, then flip it back

    return verified_dicts  
    #currently, we don't do anything if there are segments missing, later add handling logic for incomplete verification

def prepare_prompt(aligned_pairs: List[AlignedPair], prompt_template: str = ALIGN_PROMPT_TEMPLATE, indent: bool = False) -> str:
    serialized_pairs = [json.dumps(pair.serialize(i), ensure_ascii=False, indent=2 if indent else None) for i, pair in enumerate(aligned_pairs)]
    separator = "\n====================================================================================================\n\n"
    string_pairs = separator.join(serialized_pairs)
    formatted_prompt = prompt_template.format(string_pairs=string_pairs)
    return formatted_prompt

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



async def main():
    setup_logging()
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    original_tree, translation_tree = load_file_pair(file_code="301043")
    original_div0 = original_tree.find("body").find("div0")
    translation_div0 = translation_tree.find("body").find("div0")

    original_paragraphs = [Element(tag, index) for index, tag in enumerate(original_div0.find_all("p", recursive=False))]
    translation_paragraphs = [Element(tag, index) for index, tag in enumerate(translation_div0.find_all("p", recursive=False))]

    logger.info("Aligning file pair on distance...")
    aligned_pairs = align_on_distance(1, original_paragraphs, translation_paragraphs, signature_tags=["lg", "l", "q"])
    logger.info("✅ Aligned file pair")

    await save_to_file(prepare_prompt(aligned_pairs, ALIGN_PROMPT_TEMPLATE), file_name="formatted_prompt_template", include_suffix=True, include_time=True, readable=False)

    verified = await verify_aligned_pairs(aligned_pairs)

    await save_dict_to_json({"verified_pairs": verified}, file_name="verified_pairs_301043", json_dir=".", include_time=True)

if __name__ == "__main__":
    asyncio.run(main())
    