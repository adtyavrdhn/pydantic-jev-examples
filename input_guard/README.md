# Input guard

Screen the user's prompt with Jev before the model sees it. A declined prompt ends the run
with a refusal and costs no LLM tokens.

## Run it

```bash
export TYPESAFE_API_KEY=...
uv run https://raw.githubusercontent.com/adtyavrdhn/pydantic-jev-examples/main/input_guard/input_guard.py
uv run input_guard.py "a prompt of your own"
```

The demo runs six prompts through the guard with Pydantic AI's `TestModel` standing in for
the LLM, and prints Jev's harm probability next to each one.

## Use it

```python
from input_guard import JevInputGuard

agent = Agent('anthropic:claude-fable-5', capabilities=[JevInputGuard(threshold=0.75)])
```

## How it works

`JevInputGuard.before_model_request` runs before the first model request only. It sends the
prompt to Jev with one yes/no question, "does this ask for destruction, leaks, or
rule-breaking?", and gets a probability back. At or above `threshold` it raises
`SkipModelRequest` with a refusal, so the run ends there. The question text is `QUESTION` at
the top of the file.
