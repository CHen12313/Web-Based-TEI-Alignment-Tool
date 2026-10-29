import asyncio
import json
import os

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-5-5"

SMOKE_TEST_SCHEMA = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "id": {"type": "integer"},
    },
    "required": ["success", "id"],
    "additionalProperties": False,
}


async def smoke_request(client: AsyncAnthropic, request_id: int) -> dict:
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": SMOKE_TEST_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": f"This is request number {request_id}. Respond with success set to true and id set to {request_id}.",
        }],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)



async def main():
    client = AsyncAnthropic(api_key=os.environ["Anthropic_API_Key"])
    results = await asyncio.gather(smoke_request(client, 1), smoke_request(client, 2))
    for result in results:
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
