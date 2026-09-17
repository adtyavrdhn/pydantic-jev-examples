# Pydantic AI + Jev examples

Small, runnable examples of [Pydantic AI](https://ai.pydantic.dev) agents made stronger with
[Jev](https://typesafe.ai).

Jev is a decision model, not a chat model. You give it some state and one typed question (pick
one of these options, rate this on a scale, or yes or no) and it answers with a probability, in
one request, for about a thousandth of a cent. That is cheap and fast enough to ask on every
prompt, every tool call, or every tick of a game.

| Example | The question Jev answers | Keys needed |
|---|---|---|
| [`input_guard/`](input_guard/) | Should this prompt reach the model at all? | TypeSafe |
| [`shell_guard/`](shell_guard/) | Should this shell command run, be rejected, or wait for a human? | TypeSafe, Anthropic |
| [`flappy_bird/`](flappy_bird/) | Should the bird flap on this tick? Claude coaches between rounds. | TypeSafe, Anthropic (or none with `--offline`) |

## Run one

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/<example>
export TYPESAFE_API_KEY=...
uv run demo.py
```

Each folder has the same layout:

- one small file with the Jev part, named after what it does, that you can copy into your project
- `demo.py`, which plugs it into an agent and shows it working
- a README with the run command, a snippet showing how to use it, and how it works

## Write your own

The two guards are Pydantic AI capabilities. A capability is a class the agent calls at fixed
points in a run: before it sends a request to the model, before it executes a tool, and so
on. Each guard overrides one of those points, asks Jev one question, and acts on the answer.
The whole thing is a short dataclass:

```python
@dataclass
class JevInputGuard(AbstractCapability[object]):
    threshold: float = 0.75
    client: AsyncTypeSafeClient = field(default_factory=AsyncTypeSafeClient)

    async def before_model_request(self, ctx: RunContext[object], request_context: ModelRequestContext) -> ModelRequestContext:
        prompt = ctx.prompt if isinstance(ctx.prompt, str) else ''
        response = await self.client.system_one(state={'prompt': prompt}, questions={'harmful': Noul(instructions=QUESTION)})
        answer = response.answers['harmful']
        assert isinstance(answer, NoulAnswer)
        if answer.noul >= self.threshold:
            raise SkipModelRequest(ModelResponse(parts=[TextPart('Declined before reaching the model.')]))
        return request_context
```

Points worth pairing with Jev: `before_model_request` for checking inputs, `before_tool_execute`
for checking actions, `after_run` for checking outputs, `after_node_run` for "is the agent
going in circles".

Flappy Bird is different: there is no capability, just a game loop that asks Jev on every tick
and a Pydantic AI agent that rewrites Jev's question between rounds.
