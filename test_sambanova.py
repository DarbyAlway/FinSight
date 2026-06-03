"""Quick test: verify SambaNova API key and tool calling."""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_URL = "https://api.sambanova.ai/v1"
API_KEY = os.getenv("SAMBANOVA_API_KEY")

MODELS = [
    "gpt-oss-120b",
    "Meta-Llama-3.3-70B-Instruct",
]

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

def test_basic(model: str) -> None:
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            temperature=0.0,
            max_tokens=10,
        )
        reply = (r.choices[0].message.content or "").strip()
        tokens = r.usage.total_tokens if r.usage else "?"
        print(f"  [{model}] OK — reply={reply!r}  tokens={tokens}")
    except Exception as e:
        print(f"  [{model}] FAIL — {e}")


def test_tool_calling(model: str) -> None:
    tools = [{
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Get stock price",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    }]
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "What is the price of AAPL?"}],
            tools=tools,
            tool_choice="required",
            temperature=0.0,
        )
        msg = r.choices[0].message
        if msg.tool_calls:
            call = msg.tool_calls[0]
            print(f"  [{model}] Tool call OK — {call.function.name}({call.function.arguments})")
        else:
            print(f"  [{model}] No tool call — content={msg.content!r}")
    except Exception as e:
        print(f"  [{model}] Tool call FAIL — {e}")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: SAMBANOVA_API_KEY not set in .env")
        exit(1)

    print(f"Using key: {API_KEY[:8]}...  base_url={BASE_URL}\n")

    print("=== Basic connectivity ===")
    for m in MODELS:
        test_basic(m)

    print("\n=== Tool calling (gpt-oss-120b) ===")
    test_tool_calling("gpt-oss-120b")

    print("\n=== Tool calling (Meta-Llama-3.3-70B-Instruct) ===")
    test_tool_calling("Meta-Llama-3.3-70B-Instruct")
