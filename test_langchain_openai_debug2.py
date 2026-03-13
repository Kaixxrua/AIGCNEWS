import asyncio
import os
import httpx
from dotenv import load_dotenv
import logging

load_dotenv()

async def test_api():
    base_url = os.environ.get("OPENAI_BASE_URL", "https://openai.sufy.com/v1")
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("CHAT_MODEL_NAME", "openai/gpt-5.3-codex")

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    # Let's inspect what kwargs ChatOpenAI is passing
    llm = ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        streaming=True,
    )
    
    print(llm._default_params)
    
    # We will use httpx with debug logging to see the exact payload sent by openai client
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    
    try:
        async for chunk in llm.astream([HumanMessage(content="Hello")]):
            print(chunk.content or "", end="")
        print()
    except Exception as e:
        print("Error:", type(e), e)

if __name__ == "__main__":
    asyncio.run(test_api())
