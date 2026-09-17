# Flappy Bird

Jev plays. Claude coaches.

## Why Jev and not Claude

Try a chat model at the controls first:

```bash
uv run demo.py --player claude
```

Claude gets one sentence per tick. "The bird is 2 rows below the centre of the gap, falling, and
the pipe is 6 columns away." One question. Flap or not? It takes a second or two to answer. The
bird dies at the first pipe.

Now the default:

```bash
uv run demo.py
```

Same sentence. Same question. Jev answers in a few hundred milliseconds for a fraction of a
cent. A round is a few hundred decisions and costs less than a cent.

## The Jev part

All of it is in `jev_player.py`. About 50 lines:

```python
from jev_player import JevPlayer

pilot = JevPlayer()  # reads TYPESAFE_API_KEY

decision = await pilot.decide(game.state(), playbook)
game.step(decision.flap)  # decision.p_flap is Jev's probability, 0 to 1
```

Inside `decide` there is one call to Jev. The situation as a sentence. A yes/no question whose
yes side is the playbook's "flap when" list and whose no side is its "wait when" list.

## Where Claude comes in

Between rounds a Pydantic AI agent on Claude reads the replay. The last few situations and what
Jev chose in each. It rewrites the playbook. The playbook is those two lists, and they are the
two sides of Jev's question. So Claude writes Jev's question. Claude thinks once per round. Jev
decides every tick.

## Run it

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/flappy_bird
export TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=...
uv run demo.py
```

Two more ways:

```bash
uv run demo.py --player claude   # a chat model at the controls. slow. dies at the first pipe
uv run demo.py --offline         # no keys. a fake pilot and a canned coach, to see the shape
```

Set `LOGFIRE_TOKEN` too and every Jev decision shows up in Logfire. Probability, latency, cost,
nested under the coach's spans.

Options: `--rounds 3`, `--tps 3` (ticks per second, one Jev decision each), `--win 10` (end a
round after this many pipes), `--seed 7` (same pipes every round), `--coach anthropic:...`,
`--quiet` (no animation, just the table). Best at 80 columns or wider.

## What you will see

1. Round 1 uses the starter playbook. Flap when below the gap or falling fast. Jev reacts too
   late and dies on the first pipe or two.
2. The coach gets the score, how the bird died, and the last few situations with what Jev
   chose. It writes a new playbook and a one-line note on what it changed and why.
3. Rounds 2 and 3 get better. At the end you get the scores, the bill for a few hundred Jev
   decisions, and the playbooks side by side.

## Feed Jev words, not numbers

Jev judges situations. It does not do arithmetic. Give it raw numbers (`bird_y=6.0,
velocity=-0.9, gap 3-8`) and it answers close to 50/50 on everything. Give it the same
situation in words and it gets every obvious case right. `probe.py` is the experiment that
showed this. Run it with only `TYPESAFE_API_KEY`.

So the demo is built on words:

- `BirdState.describe()` in `game.py` turns the numbers into one sentence from a fixed
  vocabulary. That sentence is what Jev gets.
- `Playbook` is the two lists. `JevPlayer.decide` puts them in as the yes and no criteria.
- The coach's instructions use the same vocabulary. The replay it reads is those same
  sentences. It sees what Jev saw.

Jev returns a probability of "flap". The bird flaps at 0.5 or above.

## Files

| File | What it is | Read it if |
|---|---|---|
| `jev_player.py` | Jev at the controls | you want the Jev part |
| `game.py` | physics, the state sentence, the playbook | you want to change the game |
| `demo.py` | the coach, the other pilots, the screen | you want to change the show |
| `probe.py` | numbers vs words, eight situations three ways | you want to see why Jev gets words |
