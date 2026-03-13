import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def test_api():
    base_url = os.environ.get("OPENAI_BASE_URL", "https://openai.sufy.com/v1")
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("CHAT_MODEL_NAME", "openai/gpt-5.3-codex")

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    llm = ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        streaming=True,
        model_kwargs={"stream_options": None}
    )
    
    print("\n--- Testing Langchain Streaming with stream_options None ---")
    try:
        async for chunk in llm.astream([HumanMessage(content="Hello")]):
            print(chunk.content or "", end="")
        print()
    except Exception as e:
        print("Error:", type(e), e)

if __name__ == "__main__":
    asyncio.run(test_api())
