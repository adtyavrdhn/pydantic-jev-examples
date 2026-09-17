# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic-ai-slim[anthropic]>=2", "typesafe-sdk>=0.6", "logfire>=4"]
# ///
"""Claude coaches, Jev plays Flappy Bird.

Jev (https://typesafe.ai) answers a typed question in about a tenth of a second, for a
fraction of a cent. That is fast enough to sit inside a game loop; a chat model is not.
So Jev pilots the bird, one yes/no question per tick. Claude, as a Pydantic AI agent, is
the coach: between rounds it reads the replay and rewrites the plain-English playbook Jev
follows. Slow brain writes the strategy, fast brain plays.

Try it:

    TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=... uv run flappy_bird.py
    uv run flappy_bird.py --player claude     # the opening gag: a chat model at the controls
    uv run flappy_bird.py --offline           # no keys: fake pilot + canned coach

Set LOGFIRE_TOKEN to get one span per Jev decision with its probability, latency and cost.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Protocol

import logfire
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulAnswer

# ---------------------------------------------------------------- the game

WIDTH = 40
HEIGHT = 12  # rows 0..11; row 11 is the ground
BIRD_X = 8
GRAVITY = 0.35
FLAP_VELOCITY = -1.1
GAP = 5
PIPE_EVERY = 14
PIPE_WIDTH = 2

PHYSICS = (
    f'bird_y is the bird height: 0 is the top of the screen, {HEIGHT - 1} is the ground. '
    f'Each tick the bird falls a bit faster (velocity grows by {GRAVITY}). '
    f'A flap sets velocity to {FLAP_VELOCITY} (up): one flap lifts the bird about 1.2 rows, peaking 3 ticks later, '
    'then it falls again. Flapping on consecutive ticks keeps lifting. Positive velocity means falling. '
    'The next pipe is distance_to_pipe columns away and moves 1 column closer each tick. '
    'When distance_to_pipe is 0 or 1 the bird is inside the pipe and must be between gap_top and gap_bottom '
    '(gap_top <= bird_y < gap_bottom) or it dies. Hitting the ground also kills it.'
)


class BirdState(BaseModel):
    """What the pilot sees on every tick."""

    bird_y: float = Field(description=f'Bird height. 0 is the top, {HEIGHT - 1} is the ground.')
    velocity: float = Field(description='Positive means falling, negative means rising.')
    gap_top: int = Field(description='First open row of the next pipe gap.')
    gap_bottom: int = Field(description='First blocked row below the gap.')
    distance_to_pipe: int = Field(description='Columns until the next pipe. 0 means inside it.')
    score: int


class Playbook(BaseModel):
    """The rules the pilot reads on every tick. Short on purpose: Jev is billed per input token."""

    rules: str = Field(max_length=600, description='Plain English rules for when to flap. Numbers beat adjectives.')
    note: str = Field(max_length=200, description='One line: what changed since the last round and why.')


class Tick(BaseModel):
    frame: int
    state: BirdState
    flap: bool
    p_flap: float


class RoundResult(BaseModel):
    score: int
    frames: int
    death: str
    replay: list[Tick]
    pilot_calls: int = 0
    pilot_cost_usd: float = 0.0
    pilot_latency_ms: float = 0.0

    def summary(self, last: int = 8) -> str:
        lines = [f'score {self.score}, survived {self.frames} ticks, {self.death}.', 'Last ticks before death:']
        for t in self.replay[-last:]:
            s = t.state
            lines.append(
                f'  frame {t.frame}: bird_y={s.bird_y:.1f} velocity={s.velocity:.1f} '
                f'gap={s.gap_top}-{s.gap_bottom} distance={s.distance_to_pipe} -> '
                f'{"FLAP" if t.flap else "wait"} (p={t.p_flap:.2f})'
            )
        return '\n'.join(lines)


@dataclass
class Pipe:
    x: int
    gap_top: int
    scored: bool = False

    @property
    def gap_bottom(self) -> int:
        return self.gap_top + GAP


@dataclass
class Game:
    seed: int = 1
    bird_y: float = 5.0
    velocity: float = 0.0
    score: int = 0
    frame: int = 0
    dead: str | None = None
    pipes: list[Pipe] = field(default_factory=list)
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self.pipes = [self._new_pipe(WIDTH + i * PIPE_EVERY) for i in range(3)]

    def _new_pipe(self, x: int) -> Pipe:
        return Pipe(x=x, gap_top=self._rng.randint(1, HEIGHT - 2 - GAP))

    @property
    def next_pipe(self) -> Pipe:
        return next(p for p in self.pipes if p.x + PIPE_WIDTH - 1 >= BIRD_X)

    def state(self) -> BirdState:
        p = self.next_pipe
        return BirdState(
            bird_y=round(self.bird_y, 2),
            velocity=round(self.velocity, 2),
            gap_top=p.gap_top,
            gap_bottom=p.gap_bottom,
            distance_to_pipe=max(0, p.x - BIRD_X),
            score=self.score,
        )

    def step(self, flap: bool) -> None:
        if self.dead:
            return
        self.frame += 1
        if flap:
            self.velocity = FLAP_VELOCITY
        self.velocity += GRAVITY
        self.bird_y += self.velocity
        if self.bird_y < 0:
            self.bird_y, self.velocity = 0.0, 0.0

        for p in self.pipes:
            p.x -= 1
        if self.pipes[-1].x <= WIDTH - PIPE_EVERY:
            self.pipes.append(self._new_pipe(self.pipes[-1].x + PIPE_EVERY))
        self.pipes = [p for p in self.pipes if p.x + PIPE_WIDTH > 0]

        row = int(self.bird_y + 0.5)
        if row >= HEIGHT - 1:
            self.dead = 'hit the ground'
            return
        for p in self.pipes:
            if p.x <= BIRD_X < p.x + PIPE_WIDTH and not (p.gap_top <= row < p.gap_bottom):
                where = 'top pipe' if row < p.gap_top else 'bottom pipe'
                self.dead = f'hit the {where} (gap was rows {p.gap_top}-{p.gap_bottom - 1}, bird at row {row})'
                return
            if p.x + PIPE_WIDTH - 1 < BIRD_X and not p.scored:
                p.scored = True
                self.score += 1

    def render(self) -> list[str]:
        grid = [[' '] * WIDTH for _ in range(HEIGHT)]
        for p in self.pipes:
            for dx in range(PIPE_WIDTH):
                x = p.x + dx
                if 0 <= x < WIDTH:
                    for y in range(HEIGHT - 1):
                        if not (p.gap_top <= y < p.gap_bottom):
                            grid[y][x] = '█'
        row = min(HEIGHT - 1, max(0, int(self.bird_y + 0.5)))
        grid[row][BIRD_X] = '@'
        grid[HEIGHT - 1] = ['▔'] * WIDTH
        return [''.join(r) for r in grid]


# ---------------------------------------------------------------- the pilots

# https://typesafe.ai: $42 per billion input tokens, output free.
JEV_USD_PER_INPUT_TOKEN = 42 / 1_000_000_000


@dataclass
class Decision:
    flap: bool
    p_flap: float
    latency_ms: float
    cost_usd: float = 0.0


class Player(Protocol):
    name: str

    async def decide(self, state: BirdState, playbook: Playbook) -> Decision: ...


class JevPlayer:
    """One Noul per tick: should the bird flap right now?"""

    name = 'Jev'

    def __init__(self, client: AsyncTypeSafeClient | None = None, *, threshold: float = 0.5):
        self._client = client or AsyncTypeSafeClient()
        self.threshold = threshold

    async def decide(self, state: BirdState, playbook: Playbook) -> Decision:
        question = Noul(
            instructions={
                'question': 'Should the bird flap on this tick?',
                'how_the_game_works': PHYSICS,
                'playbook': playbook.rules,
            },
            criteria={
                'true': 'Flap now: the bird needs to go up to survive.',
                'false': 'Do not flap: let the bird fall this tick.',
            },
        )
        t0 = time.perf_counter()
        with logfire.span('jev flap? y={bird_y} gap={gap_top}-{gap_bottom} d={distance_to_pipe}', **state.model_dump()) as span:
            response = await self._client.system_one(state=state.model_dump(), questions={'flap': question})
            latency_ms = (time.perf_counter() - t0) * 1000
            answer = response.answers['flap']
            assert isinstance(answer, NoulAnswer)
            cost = (response.usage.input_tokens or 0) * JEV_USD_PER_INPUT_TOKEN
            span.set_attributes({'p_flap': answer.noul, 'latency_ms': latency_ms, 'cost_usd': cost, 'model': response.model})
        return Decision(flap=answer.noul >= self.threshold, p_flap=answer.noul, latency_ms=latency_ms, cost_usd=cost)


class FakePlayer:
    """Offline stand-in with no API key. Reads the playbook very crudely (keyword spotting) so rounds still improve."""

    name = 'Fake'

    def __init__(self, seed: int = 0):
        self._rng = random.Random(seed)

    async def decide(self, state: BirdState, playbook: Playbook) -> Decision:
        await asyncio.sleep(0.05)
        rules = playbook.rules.lower()
        target = (state.gap_top + state.gap_bottom) / 2 - 0.5
        if 'velocity >= 0' in rules or 'never flap while rising' in rules:
            want = state.velocity >= 0 and state.bird_y + state.velocity > target
        elif 'gap' in rules:
            want = state.bird_y + state.velocity * 2 > target
        else:
            want = state.bird_y > 5.5
        p = min(1.0, max(0.0, (0.8 if want else 0.2) + self._rng.uniform(-0.15, 0.15)))
        return Decision(flap=p >= 0.5, p_flap=p, latency_ms=50.0)


class FlapOrNot(BaseModel):
    flap: bool


class ClaudePlayer:
    """The opening gag: a chat model at the controls. Same game, same question, a second or two per tick."""

    name = 'Claude'

    def __init__(self, model: str):
        self._agent = Agent(
            model,
            output_type=FlapOrNot,
            instructions=f'You are piloting Flappy Bird. {PHYSICS} Answer only with whether to flap on this tick.',
        )

    async def decide(self, state: BirdState, playbook: Playbook) -> Decision:
        t0 = time.perf_counter()
        result = await self._agent.run(f'Playbook: {playbook.rules}\nState: {state.model_dump_json()}')
        latency_ms = (time.perf_counter() - t0) * 1000
        cost = float(result.usage.cost or 0)
        return Decision(flap=result.output.flap, p_flap=1.0 if result.output.flap else 0.0, latency_ms=latency_ms, cost_usd=cost)


# ---------------------------------------------------------------- the coach

STARTER = Playbook(
    rules='Flap whenever the bird is below the middle of the screen.',
    note='Starter playbook. Nobody has coached Jev yet.',
)

COACH_INSTRUCTIONS = f"""You coach Jev, a tiny, very fast decision model that pilots Flappy Bird.
You cannot play yourself. You write the playbook: plain English rules Jev reads on every tick
together with the current state (bird_y, velocity, gap_top, gap_bottom, distance_to_pipe, score).
Jev answers one yes/no question per tick: flap or not.

How the game works: {PHYSICS}

After each round you get the score, how the bird died, and the last ticks before it died.
Write the next playbook. Keep it short and concrete: thresholds and numbers beat adjectives.
Change one or two things at a time and say what you changed in the note."""


def make_coach(model: str) -> Agent[None, Playbook]:
    return Agent(model, output_type=Playbook, instructions=COACH_INSTRUCTIONS)


_CANNED = [
    Playbook(
        rules=(
            'Aim for the middle of the gap: target = (gap_top + gap_bottom) / 2 - 0.5. '
            'Flap if bird_y + velocity * 2 > target. Otherwise wait.'
        ),
        note='Round 1 flapped constantly and hit the top pipe. Now aim for the gap centre and look 2 ticks ahead.',
    ),
    Playbook(
        rules=(
            'target = (gap_top + gap_bottom) / 2 - 0.5. Only flap when velocity >= 0 (the bird is not already rising) '
            'and bird_y + velocity > target. Never flap while rising.'
        ),
        note='Still overshooting into the top pipe: it flapped while already rising. Now one flap at a time.',
    ),
]


def make_offline_coach() -> Agent[None, Playbook]:
    """A canned coach for runs without an Anthropic key: returns the next canned playbook each round."""
    calls = {'n': 0}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        playbook = _CANNED[min(calls['n'], len(_CANNED) - 1)]
        calls['n'] += 1
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=playbook.model_dump())])

    return Agent(FunctionModel(respond, model_name='offline-coach'), output_type=Playbook, instructions=COACH_INSTRUCTIONS)


# ---------------------------------------------------------------- the show

CLEAR = '\x1b[H\x1b[J'


def bar(p: float, width: int = 12) -> str:
    filled = int(round(p * width))
    return '▓' * filled + '░' * (width - filled)


async def play_round(
    game: Game, player: Player, playbook: Playbook, *, round_no: int, tick_seconds: float, quiet: bool, win: int
) -> RoundResult:
    replay: list[Tick] = []
    calls = 0
    cost = 0.0
    latency_total = 0.0
    with logfire.span('round {round_no} ({pilot})', round_no=round_no, pilot=player.name):
        while not game.dead:
            state = game.state()
            t0 = time.perf_counter()
            decision = await player.decide(state, playbook)
            calls += 1
            cost += decision.cost_usd
            latency_total += decision.latency_ms
            replay.append(Tick(frame=game.frame, state=state, flap=decision.flap, p_flap=decision.p_flap))
            game.step(decision.flap)
            if game.score >= win and not game.dead:
                game.dead = f'cleared {win} pipes, that is a win'

            if not quiet:
                header = (
                    f' round {round_no}   score {game.score:<3}  {player.name} p(flap) '
                    f'{bar(decision.p_flap)} {decision.p_flap:.2f}   {decision.latency_ms:5.0f} ms   ${cost:.5f}'
                )
                sys.stdout.write(CLEAR + header + '\n\n' + '\n'.join(game.render()) + '\n')
                if game.dead:
                    sys.stdout.write(f'\n  {"🏆" if game.score >= win else "💥"} {game.dead}\n')
                sys.stdout.flush()
            remaining = tick_seconds - (time.perf_counter() - t0)
            if remaining > 0 and not quiet:
                await asyncio.sleep(remaining)
    return RoundResult(
        score=game.score,
        frames=game.frame,
        death=game.dead or 'survived',
        replay=replay,
        pilot_calls=calls,
        pilot_cost_usd=cost,
        pilot_latency_ms=latency_total / max(calls, 1),
    )


async def demo() -> None:
    parser = argparse.ArgumentParser(description='Claude coaches, Jev plays Flappy Bird.')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--player', choices=['jev', 'claude', 'fake'], default='jev')
    parser.add_argument('--coach', default=os.environ.get('COACH_MODEL', 'anthropic:claude-sonnet-5'))
    parser.add_argument('--offline', action='store_true', help='fake pilot + canned coach, no API keys needed')
    parser.add_argument('--seed', type=int, default=7, help='same pipes every round, so rounds are comparable')
    parser.add_argument('--fps', type=float, default=6.0)
    parser.add_argument('--win', type=int, default=15, help='stop a round after this many pipes')
    parser.add_argument('--quiet', action='store_true', help='no animation, just results')
    args = parser.parse_args()

    logfire.configure(send_to_logfire='if-token-present', console=False)
    logfire.instrument_pydantic_ai()

    if args.offline:
        player: Player = FakePlayer(seed=args.seed)
        coach = make_offline_coach()
    else:
        missing = [k for k in ('TYPESAFE_API_KEY', 'ANTHROPIC_API_KEY') if not os.environ.get(k)]
        if missing and args.player != 'fake':
            sys.exit(f'Set {" and ".join(missing)}, or run with --offline.')
        player = {'jev': lambda: JevPlayer(), 'claude': lambda: ClaudePlayer(args.coach), 'fake': lambda: FakePlayer(args.seed)}[
            args.player
        ]()
        coach = make_coach(args.coach)

    playbook = STARTER
    playbooks: list[Playbook] = []
    history: list[ModelMessage] = []
    scores: list[int] = []
    pilot_calls = 0
    pilot_cost = 0.0
    coach_cost = 0.0

    with logfire.span('flappy demo: {pilot} pilots, coach={coach}', pilot=player.name, coach=args.coach):
        for round_no in range(1, args.rounds + 1):
            playbooks.append(playbook)
            if not args.quiet:
                intro = f' round {round_no}: playbook\n\n  {playbook.rules}\n\n  ({playbook.note})\n\n  starting in 3s...\n'
                sys.stdout.write(CLEAR + intro)
                sys.stdout.flush()
                await asyncio.sleep(3)

            game = Game(seed=args.seed)
            result = await play_round(
                game, player, playbook, round_no=round_no, tick_seconds=1 / args.fps, quiet=args.quiet, win=args.win
            )
            scores.append(result.score)
            pilot_calls += result.pilot_calls
            pilot_cost += result.pilot_cost_usd
            print(
                f'\n round {round_no}: score {result.score}, {result.death}. '
                f'{result.pilot_calls} {player.name} decisions, avg {result.pilot_latency_ms:.0f} ms, '
                f'${result.pilot_cost_usd:.5f}'
            )

            if round_no == args.rounds:
                break
            print(' coach is thinking...')
            prompt = (
                f'Round {round_no} with this playbook:\n{playbook.rules}\n\n'
                f'Result: {result.summary()}\n\nWrite the playbook for round {round_no + 1}.'
            )
            run = await coach.run(prompt, message_history=history)
            history = run.all_messages()
            playbook = run.output
            coach_cost += float(run.usage.cost or 0)
            print(f' coach: {playbook.note}')
            if not args.quiet:
                await asyncio.sleep(2)

    print('\n scores by round:', ' -> '.join(str(s) for s in scores))
    print(f' {player.name} made {pilot_calls} decisions for ${pilot_cost:.5f}')
    print(f' coach ({args.coach}) cost ${coach_cost:.4f}')
    print('\n the playbooks:')
    for i, pb in enumerate(playbooks, 1):
        print(f'\n  round {i}: {pb.rules}\n          ({pb.note})')


if __name__ == '__main__':
    try:
        asyncio.run(demo())
    except KeyboardInterrupt:
        pass
