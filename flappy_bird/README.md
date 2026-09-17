# Flappy Bird

Jev plays. Claude coaches.

## Why Jev and not Claude

Try it with a chat model at the controls first:

```bash
uv run demo.py --player claude
```

Claude gets one sentence per tick, something like "The bird is 2 rows below the centre of the
gap, falling, and the pipe is 6 columns away", and one question: flap or not? It takes a second
or two to answer, and the bird dies at the first pipe.

Now run the default:

```bash
uv run demo.py
```

Same sentence, same question, but Jev answers in a few hundred milliseconds for a fraction of a
cent. A round is a few hundred decisions and costs less than a cent.

## The Jev part

All of it is in `jev_player.py`, about 50 lines. Using it looks like this:

```python
from jev_player import JevPlayer

pilot = JevPlayer()  # reads TYPESAFE_API_KEY

decision = await pilot.decide(game.state(), playbook)
game.step(decision.flap)  # decision.p_flap is Jev's probability, 0 to 1
```

Inside `decide` there is one call to Jev. It sends the situation as a sentence and a yes/no
question, where the yes side is the playbook's "flap when" list and the no side is its "wait
when" list.

## Where Claude comes in

Between rounds, a Pydantic AI agent on Claude reads the replay, which is the last few
situations and what Jev chose in each, and rewrites the playbook. The playbook is those two
lists, and they are the two sides of Jev's question. So Claude is writing Jev's question for
it. Claude thinks once per round, and Jev decides every tick.

## Run it

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/flappy_bird
export TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=...
uv run demo.py
```

Two more ways to run it:

```bash
uv run demo.py --player claude   # a chat model at the controls: slow, and it dies at the first pipe
uv run demo.py --offline         # no keys needed: a fake pilot and a canned coach, just to see the shape
```

If you set `LOGFIRE_TOKEN` as well, every Jev decision shows up in Logfire with its
probability, latency and cost, nested under the coach's spans.

Options: `--rounds 3`, `--tps 3` (ticks per second, one Jev decision each), `--win 10` (end a
round after this many pipes), `--seed 7` (same pipes every round, so rounds compare),
`--coach anthropic:...`, and `--quiet` (no animation, just the results table). The screen
looks best at 80 columns or wider.

## What you will see

1. Round 1 uses the starter playbook: flap when the bird is below the gap or falling fast. Jev
   reacts too late and dies on the first pipe or two.
2. The coach gets the score, how the bird died, and the last few situations with what Jev
   chose. It writes a new playbook and a one-line note saying what it changed and why.
3. Rounds 2 and 3 get better. At the end you get the scores, the bill for a few hundred Jev
   decisions, and all the playbooks side by side.

## Feed Jev words, not numbers

Jev judges situations. It does not do arithmetic. If you give it raw numbers like
`bird_y=6.0, velocity=-0.9, gap 3-8`, it answers close to 50/50 on everything. Give it the
same situation in words and it gets every obvious case right. `probe.py` is the small
experiment that showed this, and you can run it with only `TYPESAFE_API_KEY`.

So the demo is built around words:

- `BirdState.describe()` in `game.py` turns the numbers into one sentence from a fixed
  vocabulary. That sentence is what Jev gets.
- `Playbook` is the two lists. `JevPlayer.decide` puts them in as the yes and no sides of the
  question.
- The coach's instructions use that same vocabulary, and the replay it reads is made of those
  same sentences. It sees exactly what Jev saw.

Jev returns a probability of "flap", and the bird flaps at 0.5 or above.

## Files

| File | What it is | Read it if |
|---|---|---|
| `jev_player.py` | Jev at the controls | you want the Jev part |
| `game.py` | the physics, the state sentence, the playbook | you want to change the game |
| `demo.py` | the coach, the other pilots, the animated screen | you want to change the show |
| `probe.py` | numbers vs words: eight situations, three ways of describing them | you want to see why Jev gets words |
