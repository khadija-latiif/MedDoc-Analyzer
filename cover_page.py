import json
from openai import OpenAI
from prompts import get_cover_page_prompt
from batch_split import parse_llm_json
import os
from dotenv import load_dotenv

load_dotenv()


# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_cover_page_with_llm(first_page_text):
    """Analyze first page to detect if it's a cover sheet and extract sender info/comments."""
    try:
        prompt = get_cover_page_prompt(first_page_text)

        model = os.getenv("OPENAI_MODEL", "gpt-4o")
        result = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )

        llm_output = result.choices[0].message.content
        parsed = parse_llm_json(llm_output)

        if parsed is None:
            print("❌ Failed to parse LLM JSON for cover page detection")
            print("Raw output:")
            print(llm_output)
        else:
            print("✅ Cover Page Analysis:")
            print(json.dumps(parsed, indent=2))

        return parsed

    except Exception as e:
        print(f"❌ Error analyzing cover page: {e}")
        return None
