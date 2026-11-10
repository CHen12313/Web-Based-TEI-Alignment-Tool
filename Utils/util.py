from datetime import datetime
import logging
from pathlib import Path
import json
import re
import textwrap
from Utils.storage import make_storage
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
env_path = Path(__file__).resolve().parents[1] / ".env"
storage_obj = make_storage()

async def load_file_content(file_directory) ->str:
    return await storage_obj.read_text(file_directory)

def unescape_newlines(text: str) -> str:
    """Turn literal '\\n' escape sequences (as produced by json.dumps on text that contains
    real newlines) into actual line breaks, so a saved debug dump reads as wrapped lines
    instead of a wall of "\\n" characters."""
    return text.replace("\\n", "\n")

def wrap_long_lines(text: str, width: int = 120) -> str:
    """Re-wrap any line longer than `width` characters onto several lines, breaking only on
    whitespace. A long JSON string value (e.g. a paragraph's full tag_string) is otherwise a
    single line that reads as a wall of text requiring horizontal scrolling."""
    wrapped_lines = []
    for line in text.splitlines():
        if len(line) > width:
            wrapped_lines.extend(textwrap.wrap(line, width=width, break_long_words=False, break_on_hyphens=False))
        else:
            wrapped_lines.append(line)
    return "\n".join(wrapped_lines)

async def save_to_file(text: str, file_name, output_directory: str = ".", include_suffix: bool = False, include_time: bool = False, readable: bool = False) -> str:
    output_dir = output_directory

    file_key = f"{output_dir}/{file_name}{get_suffix(include_time) if include_suffix else ""}.txt"

    await storage_obj.save_text(file_key, wrap_long_lines(unescape_newlines(text)) if readable else text)
    #logger.info(f"File saved to: {file_key}")
    return file_key


_datetime_string_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+\d{2}:\d{2}|Z)?$")

def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

def _restore_datetime_strings(parsed_dict: dict) -> dict:
    for key, value in parsed_dict.items():
        if isinstance(value, str) and _datetime_string_pattern.match(value):
            try:
                parsed_dict[key] = datetime.fromisoformat(value)
            except ValueError:
                pass
    return parsed_dict

async def save_dict_to_json(new_data: dict, file_name : str, json_dir: str, include_suffix: bool = False, include_time: bool = False) -> str:
    """
    Merge `new_data` into the JSON object stored at `json_dir/file_name`
    (creating it if missing), then write it back through `storage_obj`
    so this works against both the local and S3 backends.

    `datetime` values are encoded as ISO-8601 strings and are decoded
    back into `datetime` automatically by `read_from_json`.
    """

    file_key = f"{json_dir}/{file_name}{get_suffix(include_time) if include_suffix else ""}.json"

    data = await read_from_json(file_key) or {}
    data.update(new_data)

    payload = json.dumps(data, indent=4, ensure_ascii=False, default=_json_default)
    await storage_obj.save_text(file_key, payload)

    return file_key


async def read_from_json(json_key : str) -> dict:
    """
    Load the JSON object stored at `json_key` as a dict through `storage_obj`.
    Returns {} if it doesn't exist.

    ISO-8601 strings produced by `save_dict_to_json`'s `datetime` encoding
    are decoded back into `datetime` objects.
    """
    try:
        text = await storage_obj.read_text(json_key)
    except FileNotFoundError:
        return None
    
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        else:
            raise

    return json.loads(text, object_hook=_restore_datetime_strings)
    

def format_dict(data: dict) -> str:
    """Format a dict into a human-readable multi-line string with clear visual separation per key."""
    SEPARATOR = "=" * 70
    lines = []
    for key, value in data.items():
        lines.append(SEPARATOR)
        lines.append(f"  {key}")
        lines.append(SEPARATOR)
        if isinstance(value, (dict, list)):
            val_str = json.dumps(value, indent=2, default=str)
        else:
            val_str = str(value)
        for line in val_str.splitlines():
            lines.append(f"  {line}")
        lines.append("")
    return "\n".join(lines)

def get_suffix(include_time : bool = False):
    """
    this gives you the date suffix in the form of:\n
    _{date}_{time} #time is optional and off my default
    """

    today = datetime.now().strftime("%Y-%m-%d")
    now = f"_{datetime.now().strftime("%H-%M-%S")}"

    suffix = f"_{today}{now if include_time else ""}"
    return suffix

if __name__ == "__main__":
    import asyncio
    base_path = Path(__file__).resolve().parent.parent
    print(base_path)
    print(asyncio.run(save_to_file("abc", f"Error_log", base_path / "File_Outputs"/"Test User"/"Test", True)))
    #pass