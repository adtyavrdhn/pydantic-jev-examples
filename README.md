# Pydantic AI + Jev examples

Small Pydantic AI capabilities made stronger with [Jev](https://typesafe.ai). One folder per
example, one file per capability. Run it with one command, then copy it into your project.

Jev is a decision model, not a chat model. You give it state and a typed question (a choice, a
score, or a yes/no) and it returns an answer with a calibrated probability, in one request, for
about a thousandth of a cent. Cheap enough to ask on every prompt and every tool call.

| Example | What Jev decides | Keys |
|---|---|---|
| [`input_guard/`](input_guard/) | Should this prompt reach the model at all? | TypeSafe |
| [`shell_guard/`](shell_guard/) | Should this shell command run, be rejected, or wait for a human? | TypeSafe, Anthropic |

Each folder's README has the run command. They all start the same way:

```bash
export TYPESAFE_API_KEY=...
uv run https://raw.githubusercontent.com/adtyavrdhn/pydantic-jev-examples/main/<example>/<example>.py
```

## Make your own

Every file has the same shape: a dataclass that subclasses `AbstractCapability`, one hook, one
Jev question, and a `demo()` under `if __name__ == '__main__'`. The prompt is the criteria
text at the top. The strictness is a `threshold=` argument.

Hooks worth pairing with Jev: `before_model_request` for inputs, `before_tool_execute` for
actions, `after_run` for outputs, `after_node_run` for "is the agent going in circles".
