import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from model_runners import AnthropicRunner, GeminiApiRunner, OpenAICompatibleRunner
from test_harness import NalanaTestHarness


def main():
    missing = [var for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY") if not os.environ.get(var)]
    if missing:
        print(f"Missing API keys: {', '.join(missing)}")
        sys.exit(1)

    fixture_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample_cases_v2.json")

    runners = [
        GeminiApiRunner(model_id="gemini-2.5-pro"),
        AnthropicRunner(model_id="claude-sonnet-4-6"),
        AnthropicRunner(model_id="claude-opus-4-7"),
        OpenAICompatibleRunner(model_id="gpt-5.4"),
    ]

    harness = NalanaTestHarness(fixture_path)
    runs = harness.run_models(runners)

    print("\n--- Evaluation Complete ---")
    for run in runs:
        print(f"{run.model_id}: {run.report_markdown_path}")


if __name__ == "__main__":
    main()
