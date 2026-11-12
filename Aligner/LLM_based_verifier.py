import asyncio
import json
import os
import sys
import warnings
import logging
from random import uniform

from pathlib import Path
from typing import List

from anthropic import AsyncAnthropic, APIError, APIStatusError
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
TOKEN_PER_PAIR = 1024
FATAL_STATUS_CODES: set[int] = {400, 401, 403, 404, 413}

async def verify_segment(start_index:int, 
                         end_index:int, 
                         pairs_list: List[AlignedPair],
                         prompt_template: str, 
                         client: AsyncAnthropic, 
                         max_token: int, 
                         max_retry: int = 2, 
                         base_delay: float = 1.0,
                         increase_max_token_retry: bool = False) -> dict | None:
    end_index = min(end_index, len(pairs_list))
    logger.info(f"Preparing prompt for segment: {start_index} - {end_index}...")
    formatted_prompt: str = await prepare_prompt(pairs_list[start_index:end_index], prompt_template, start_index=start_index)
    logger.info(f"🟢 Prompt prepared for segment: {start_index} - {end_index}")

    logger.info(f"Issuing API call for segment: {start_index} - {end_index}...")

    for attempt in range(max_retry + 1):
        if attempt != 0: logger.info(f"⚠️ Retry [{attempt}/{max_retry}] for segment: {start_index} - {end_index}...") 
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=max_token,
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
                
        except StopIteration as e:
            out_text = "|".join([block.type for block in response.content])
            if response.stop_reason:
                logger.warning(f"⚠️ LLM stopped reasoning: {response.stop_reason} {out_text}")
            if response.stop_reason == "max_tokens" and increase_max_token_retry:
                max_token += TOKEN_PER_PAIR #give it more token to retry again
                logger.warning(f"⚠️ Max token increased to {max_token}, retrying...")

            #await save_to_file(out_text, file_name="StopIteration_Exception_LLM_verifier", output_directory="Error_Logs/verifier", include_suffix=True, include_time=True, readable=False)
            continue
        
        except json.JSONDecodeError as e:
            logger.warning(f"🔴 JSON Decode Error while attempting to parse response for segment: {start_index} - {end_index}.")
            #could be LLM goofing with the schema, so an immediate retry to have it produce a hopefully good response
            await save_to_file(e, file_name="JSONDecodeError_log_LLM_verifier", output_directory="Error_Logs/verifier", include_suffix=True, include_time=True, readable=False)
            if attempt == max_retry:
                logger.error(f"❌ Segment {start_index}-{end_index} failed after {max_retry} attempts: {e}")
                return None

        except APIStatusError as e:
            error_code: int = e.status_code
            error_body: dict | None = e.body
            logger.exception(f"🔴 API Error while attempting to verify segment: {start_index} - {end_index}.")
            await save_to_file(e, file_name="APIError_log_LLM_verifier", output_directory="Error_Logs/verifier", include_suffix=True, include_time=True, readable=False)

            if error_code in FATAL_STATUS_CODES:
                return None

            delay = base_delay * (2 ** (attempt - 1) + uniform(0, 0.5))

            if attempt == max_retry:
                logger.error(f"❌ Segment {start_index}-{end_index} failed after {max_retry} attempts: {e}")
                return None
            
            #back off for some time and try again later, the more it fails, the longer to wait, wait time grows in power of 2 of attempts
            await asyncio.sleep(delay) 

        except APIError as e:
            logger.exception(f"🔴 API Error while attempting to verify segment: {start_index} - {end_index}.")
            await save_to_file(e, file_name="APIError_log_LLM_verifier", output_directory="Error_Logs/verifier", include_suffix=True, include_time=True, readable=False)

            return None


async def prepare_prompt(aligned_pairs: List[AlignedPair], 
                         prompt_template: str = ALIGN_PROMPT_TEMPLATE, 
                         indent: bool = False, start_index: int = 0) -> str:
    serialized_pairs = [json.dumps(pair.serialize(start_index + i), ensure_ascii=False, indent=2 if indent else None) for i, pair in enumerate(aligned_pairs)]
    separator = "\n====================================================================================================\n\n"
    string_pairs = separator.join(serialized_pairs)
    formatted_prompt = prompt_template.format(string_pairs=string_pairs)
    await save_to_file(formatted_prompt, file_name=f"formatted_prompt_template_segment_{start_index}-{start_index+len(aligned_pairs)}", 
                 output_directory="Formatted_Prompts", include_suffix=True, include_time=True, readable=False)
    return formatted_prompt

async def verify_aligned_pairs(aligned_pairs: List[AlignedPair], 
                               client: AsyncAnthropic | None = None, 
                               prompt_template: str = ALIGN_PROMPT_TEMPLATE, 
                               segment_size: int = 3) -> List[dict]:
    if not client:
        api_key = os.environ["ANTHROPIC_API_KEY"]
        client = AsyncAnthropic(api_key=api_key)

    logger.info(f"🏁 Start verifying {len(aligned_pairs)} pairs with LLM...")
    verified_segments = await asyncio.gather(
        *(verify_segment(i, i + segment_size, aligned_pairs, prompt_template, client, max_token=segment_size*TOKEN_PER_PAIR) 
                        for i in range(0, len(aligned_pairs), segment_size))
    )

    succeeded_segments = len([segment for segment in verified_segments if segment is not None])

    logger.info(f"✅ Verification complete. Succeeded Segments: {succeeded_segments} | Total Segments: {-(-len(aligned_pairs) // segment_size)}")
    #this is to round UP to the nearest integer, floor division rounds towards negative inf, so flip it to negative for the division, then flip it back

    return verified_segments  
    #currently, we don't do anything if there are segments missing, later add handling logic for incomplete verification

async def main():
    setup_logging()
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

    original_tree, translation_tree = load_file_pair(file_code="301042")
    original_div0 = original_tree.find("body").find("div0")
    translation_div0 = translation_tree.find("body").find("div0")

    original_paragraphs = [Element(tag, index) for index, tag in enumerate(original_div0.find_all("p", recursive=False))]
    translation_paragraphs = [Element(tag, index) for index, tag in enumerate(translation_div0.find_all("p", recursive=False))]

    logger.info("Aligning file pair on distance...")
    aligned_pairs = align_on_distance(1, original_paragraphs, translation_paragraphs, signature_tags=["lg", "l", "q"])
    logger.info("✅ Aligned file pair")

    verified = await verify_aligned_pairs(aligned_pairs, segment_size=8)

    await save_dict_to_json({"verified_pairs": verified}, file_name="verified_pairs_301043", json_dir="LLM_Responses", include_suffix=True, include_time=True)

if __name__ == "__main__":
    asyncio.run(main())
    