# Flappy Bird

Claude coaches, Jev plays. Jev pilots the bird with one yes/no question per tick. Between
rounds a Pydantic AI agent on Claude reads the replay and rewrites the plain-English playbook
Jev follows. Slow brain writes the strategy, fast brain plays.

## Run it

```bash
export TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=...
uv run https://raw.githubusercontent.com/adtyavrdhn/pydantic-jev-examples/main/flappy_bird/flappy_bird.py
```

```bash
uv run flappy_bird.py --player claude   # the opening gag: a chat model at the controls, one pipe if lucky
uv run flappy_bird.py --offline         # no keys: fake pilot + canned coach, shows the shape of the demo
```

Set `LOGFIRE_TOKEN` and every Jev decision becomes a span with its probability, latency and cost,
under the coach's spans.

Knobs: `--rounds 3`, `--fps 6`, `--win 15` (stop a round after this many pipes), `--seed 7`
(same pipes every round so rounds compare), `--coach anthropic:...`, `--quiet`.

## What happens

1. Round 1 uses the starter playbook: "flap whenever the bird is below the middle of the
   screen". Jev flaps constantly and hits the top pipe.
2. The coach gets the score, the cause of death and the last ticks, and writes a new playbook.
   Its note says what changed and why.
3. Rounds 2 and 3 get better. At the end you see the scores, the bill for a few hundred Jev
   decisions, and all three playbooks side by side.

## Where Pydantic AI is

- `BirdState`, `Playbook` and `RoundResult` are Pydantic models. Jev gets `state.model_dump()`.
- The coach is `Agent(model, output_type=Playbook)`. A playbook that is missing a field or is
  over the length cap is rejected and the model is asked again. The cap is there because Jev
  is billed per input token and reads the playbook on every tick.
- `coach.run(..., message_history=history)` carries earlier rounds forward, so the coach
  remembers what it already tried.
- `--offline` swaps the coach's model for a `FunctionModel` that returns canned playbooks.
- `ClaudePlayer` is the same `Agent` class with `output_type=FlapOrNot`, asked once per tick.

## Where Jev is

`JevPlayer.decide`: one `Noul` whose instructions carry the physics and the playbook, with the
`BirdState` as the state. `answer.noul` is the probability of "flap"; the bird flaps at 0.5.
