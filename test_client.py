import os

from utils import setup_utf8, load_env

setup_utf8()
load_env()

from deepseek_client import login, create_session, collect_response

EMAIL    = os.environ.get("DEEPSEEK_EMAIL", "")
PASSWORD = os.environ.get("DEEPSEEK_PASSWORD", "")

def test():
    print("=== TEST DEEPSEEK CLIENT ===\n")

    print("[1] Logging in...")
    token = login(email=EMAIL, password=PASSWORD)
    print(f"    Token: {token[:30]}...\n")

    print("[2] Creating session...")
    session_id = create_session(token)
    print(f"    Session ID: {session_id}\n")

    print("[3] Sending message: 'Hello! Who are you?'")
    result = collect_response(
        token=token,
        session_id=session_id,
        prompt="Human: Hello! Who are you?\n\nAssistant:",
        model="deepseek-v4-flash",
        thinking=False,
    )

    print(f"\n=== RESULT ===")
    print(f"Text: {result['text']}")
    if result.get('thinking'):
        print(f"Thinking: {result['thinking'][:100]}...")
    print(f"Finish reason: {result['finish_reason']}")

    print("\n[4] Session kept alive. Done!")

if __name__ == "__main__":
    test()
