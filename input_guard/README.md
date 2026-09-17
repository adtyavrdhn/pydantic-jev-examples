# Input guard

Ask Jev whether the user's prompt should reach the model at all. A declined prompt ends the
run with a short refusal and costs no LLM tokens.

## Use it

`input_guard.py` is the whole thing, under 50 lines. Add it to any agent:

```python
from pydantic_ai import Agent
from input_guard import JevInputGuard

agent = Agent('anthropic:claude-fable-5', capabilities=[JevInputGuard(threshold=0.75)])
```

Jev gives a probability that the prompt is harmful. At or above `threshold` the prompt is
declined. Lower the threshold to be stricter.

## Run the demo

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/input_guard
export TYPESAFE_API_KEY=...
uv run demo.py
uv run demo.py "a prompt of your own"
```

The demo sends six prompts through the guard and prints Jev's harm probability next to each
one. It uses Pydantic AI's built-in `TestModel` in place of a real LLM, so it needs only the
TypeSafe key.

## How it works

Pydantic AI calls `before_model_request` on the guard just before it sends a request to the
model. The guard only acts on the first request of a run. It sends the prompt to Jev with one
yes/no question, "does this ask for destruction, leaks, or rule-breaking?", and gets a
probability back. Above the threshold it raises `SkipModelRequest` with a refusal message, so
the run ends there without the model ever seeing the prompt.

The question is the `QUESTION` string at the top of the file. Change it to change what counts
as harmful.

## Files

| File | What it is |
|---|---|
| `input_guard.py` | the guard |
| `demo.py` | six prompts through the guard |
