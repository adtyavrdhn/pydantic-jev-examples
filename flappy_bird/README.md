# Flappy Bird

Jev plays Flappy Bird. Claude coaches it between rounds.

Every tick of the game, Jev is shown one sentence ("The bird is 2 rows below the centre of
the gap, falling, and the pipe is 6 columns away") and asked one yes/no question: flap or not?
It answers in a few hundred milliseconds for a fraction of a cent, which is fast and cheap
enough to sit inside a game loop. A chat model is not.

Between rounds, a Pydantic AI agent on Claude reads the replay and rewrites the playbook. The
playbook is two short lists, "flap when" and "wait when", and those lists become the yes and
no sides of Jev's question. Claude writes the strategy, Jev plays it.

## The Jev part

All of it is in `jev_player.py`, about 50 lines. Using it looks like this:

```python
from jev_player import JevPlayer

pilot = JevPlayer()  # reads TYPESAFE_API_KEY

decision = await pilot.decide(game.state(), playbook)
game.step(decision.flap)  # decision.p_flap is Jev's probability, 0 to 1
```

## Run it

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/flappy_bird
export TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=...
uv run demo.py
```

Two more ways to run it:

```bash
uv run demo.py --player claude   # a chat model at the controls: slow, and it dies at the first pipe
uv run demo.py --offline         # no keys needed: a fake pilot and a canned coach, to see the shape
```

Set `LOGFIRE_TOKEN` as well and every Jev decision shows up in Logfire with its probability,
latency and cost, nested under the coach's spans.

Options: `--rounds 3`, `--tps 3` (game ticks per second, one Jev decision each), `--win 10`
(end a round after this many pipes), `--seed 7` (same pipes every round, so rounds compare),
`--coach anthropic:...`, `--quiet` (no animation, just the results table). The screen is best
at 80 columns or wider.

## What you will see

1. Round 1 uses the starter playbook: flap when the bird is below the gap or falling fast. Jev
   reacts too late and dies on the first pipe or two.
2. The coach gets the score, how the bird died, and the last few situations with what Jev
   chose. It writes a new playbook and a one-line note saying what it changed and why.
3. Rounds 2 and 3 get better. At the end you get the scores, the bill for a few hundred Jev
   decisions, and all the playbooks side by side.

## How Jev is fed

Jev judges situations. It does not do arithmetic. Given raw numbers (`bird_y=6.0,
velocity=-0.9, gap 3-8`) it answers close to 50/50 for everything. Given the same situation
in words it gets every obvious case right. `probe.py` is the small experiment that showed this;
run it with only `TYPESAFE_API_KEY` to see for yourself.

So the demo is built around words:

- `BirdState.describe()` in `game.py` turns the numbers into one sentence from a fixed
  vocabulary. That sentence is what Jev receives.
- `Playbook` is the two lists. `JevPlayer.decide` puts them in as the yes and no criteria
  of the question, so the coach is writing Jev's question for it.
- The coach's instructions include that same vocabulary, and the replay it reads is made of
  those same sentences. It sees exactly what Jev saw.

Jev returns a probability of "flap". The bird flaps at 0.5 or above.

## Files

| File | What it is | Read it if |
|---|---|---|
| `jev_player.py` | Jev at the controls | you want to see the Jev integration |
| `game.py` | the game: physics, the state sentence, the playbook | you want to change the game |
| `demo.py` | the coach, the other pilots, the animated screen | you want to change the show |
| `probe.py` | numbers vs words: eight situations, three ways of describing them | you want to see why Jev gets words |
