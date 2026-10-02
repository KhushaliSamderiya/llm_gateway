from dotenv import dotenv_values
from openai import AuthenticationError, NotFoundError, OpenAI

BASE_URL = "http://localhost:8000/v1"
key = dotenv_values(".env")["GATEWAY_TEST_KEY"]

# The only gateway-specific parts are base_url and the key.
client = OpenAI(base_url=BASE_URL, api_key=key)

for model in ["mock", "gemini-3.5-flash-lite"]:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Explain DNS in one sentence."}],
        temperature=0,
    )
    print(f"\n{model}")
    print("  answer:", resp.choices[0].message.content)
    print("  tokens:", resp.usage.prompt_tokens, "in,", resp.usage.completion_tokens, "out")

# Errors should map to the SDK's own exception types.
try:
    OpenAI(base_url=BASE_URL, api_key="gw_wrong").chat.completions.create(
        model="mock", messages=[{"role": "user", "content": "hi"}]
    )
except AuthenticationError as exc:
    print("\nbad key  -> AuthenticationError:", exc.status_code)

try:
    client.chat.completions.create(
        model="gpt-99", messages=[{"role": "user", "content": "hi"}]
    )
except NotFoundError as exc:
    print("bad model -> NotFoundError:", exc.status_code)
