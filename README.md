# Pydantic AI + Jev examples

Small Pydantic AI capabilities made stronger with [Jev](https://typesafe.ai). One folder per
example. Each has the capability in one file, a `demo.py` that plugs it into an agent, and a
README. Run the demo, then copy the capability file into your project.

Jev is a decision model, not a chat model. You give it state and a typed question (a choice, a
score, or a yes/no) and it returns an answer with a calibrated probability, in one request, for
about a thousandth of a cent. Cheap enough to ask on every prompt and every tool call.

| Example | What Jev decides | Keys |
|---|---|---|
| [`input_guard/`](input_guard/) | Should this prompt reach the model at all? | TypeSafe |
| [`shell_guard/`](shell_guard/) | Should this shell command run, be rejected, or wait for a human? | TypeSafe, Anthropic |
| [`flappy_bird/`](flappy_bird/) | Should the bird flap on this tick? Jev plays, a Pydantic AI agent on Claude coaches it between rounds. | TypeSafe, Anthropic |

Each folder's README has the run command. They all start the same way:

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/<example>
export TYPESAFE_API_KEY=...
uv run demo.py
```

## Make your own

Every guard has the same shape: a dataclass that subclasses `AbstractCapability`, one hook, one
Jev question, and a `demo()` under `if __name__ == '__main__'`. (Flappy Bird is the odd one out:
no capability, just a game loop that asks Jev every tick.) The prompt is the criteria
text at the top. The strictness is a `threshold=` argument.

Hooks worth pairing with Jev: `before_model_request` for inputs, `before_tool_execute` for
actions, `after_run` for outputs, `after_node_run` for "is the agent going in circles".
