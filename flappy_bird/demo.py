# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic-ai-slim[anthropic]>=2", "typesafe-sdk>=0.6", "logfire>=4", "rich"]
# ///
"""Claude coaches, Jev plays Flappy Bird.

Jev (https://typesafe.ai) answers a typed question in about a tenth of a second, for a
fraction of a cent. That is fast enough to sit inside a game loop; a chat model is not.
So Jev pilots the bird, one yes/no question per tick. Code describes the situation in words
("2 rows below the centre of the gap, falling") and the playbook is the yes/no criteria of
Jev's question. Claude, as a Pydantic AI agent, is the coach: between rounds it reads the
replay and rewrites the playbook. Slow brain writes the strategy, fast brain plays.

Try it:

    TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=... uv run demo.py
    uv run demo.py --player claude     # the opening gag: a chat model at the controls
    uv run demo.py --offline           # no keys: fake pilot + canned coach

Set LOGFIRE_TOKEN to get one span per Jev decision with its probability, latency and cost.

Files: jev_player.py is the Jev part, game.py is the game, this file is the coach and the screen.
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
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from game import PHYSICS, VOCABULARY, WIDTH, BirdState, Game, Playbook, RoundResult, Tick
from jev_player import Decision, JevPlayer

# ---------------------------------------------------------------- the other pilots


class Player(Protocol):
    name: str

    async def decide(self, state: BirdState, playbook: Playbook) -> Decision: ...


class FakePlayer:
    """Offline stand-in with no API key. Reads the playbook very crudely (keyword spotting) so rounds still improve."""

    name = 'Fake'

    def __init__(self, seed: int = 0):
        self._rng = random.Random(seed)

    async def decide(self, state: BirdState, playbook: Playbook) -> Decision:
        await asyncio.sleep(0.05)
        flap_when, wait_when = ' '.join(playbook.flap_when).lower(), ' '.join(playbook.wait_when).lower()
        target = (state.gap_top + state.gap_bottom) / 2 - 0.5
        if 'rising' in wait_when:
            want = state.velocity >= 0 and state.bird_y + state.velocity > target
        elif 'gap' in flap_when:
            want = state.bird_y + state.velocity * 2 > target
        else:
            want = state.velocity > 1.0 or state.bird_y > state.gap_bottom - 0.5
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
        result = await self._agent.run(f'{playbook.pretty()}\nSituation: {state.describe()}')
        latency_ms = (time.perf_counter() - t0) * 1000
        cost = float(result.usage.cost or 0)
        return Decision(
            flap=result.output.flap, p_flap=1.0 if result.output.flap else 0.0, latency_ms=latency_ms, cost_usd=cost
        )


# ---------------------------------------------------------------- the coach

STARTER = Playbook(
    flap_when=['the bird is below the bottom of the gap', 'the bird is falling fast'],
    wait_when=['the bird is inside the gap', 'the bird is rising'],
    note='Starter playbook. Nobody has coached Jev yet. It only reacts once it is already too low.',
)

COACH_INSTRUCTIONS = f"""You coach Jev, a tiny, very fast decision model that pilots Flappy Bird.
You cannot play yourself. Every tick Jev is shown the situation as one sentence and asked one
yes/no question: flap or not. Your playbook is the yes and no criteria of that question:
`flap_when` lists situations in which to flap, `wait_when` lists situations in which to wait.

Jev is a judge, not a calculator. It cannot evaluate formulas or thresholds on raw numbers.
It recognises situations described in words, so write each criterion as a situation using the
same vocabulary it sees. {VOCABULARY}

How the game works: {PHYSICS}

After each round you get the score, how the bird died, and the last situations before it died
with what Jev chose. Write the next playbook. Keep each list to a few short items, make the two
lists clearly different from each other, change one or two things at a time, and say what you
changed in the note."""


def make_coach(model: str) -> Agent[None, Playbook]:
    return Agent(model, output_type=Playbook, instructions=COACH_INSTRUCTIONS)


_CANNED = [
    Playbook(
        flap_when=['the bird is below the centre of the gap', 'the bird is falling fast'],
        wait_when=['the bird is above the centre of the gap', 'the bird is above the top of the gap'],
        note='It ignored where the gap was. Now it aims for the centre of the gap.',
    ),
    Playbook(
        flap_when=['the bird is below the centre of the gap and not rising', 'the bird is falling fast'],
        wait_when=['the bird is rising', 'the bird is above the centre of the gap'],
        note='It flapped while already rising and overshot. Now it waits whenever it is rising.',
    ),
]


def make_offline_coach() -> Agent[None, Playbook]:
    """A canned coach for runs without an Anthropic key: returns the next canned playbook each round."""
    calls = {'n': 0}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        playbook = _CANNED[min(calls['n'], len(_CANNED) - 1)]
        calls['n'] += 1
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=playbook.model_dump())])

    return Agent(
        FunctionModel(respond, model_name='offline-coach'), output_type=Playbook, instructions=COACH_INSTRUCTIONS
    )


# ---------------------------------------------------------------- the show

RENDER_FPS = 30
console = Console()


@dataclass
class View:
    """Everything the screen shows. The game loop writes it; rich reads it 30 times a second."""

    pilot: str
    coach: str
    round_no: int = 0
    playbook: Playbook = field(default_factory=lambda: STARTER)
    game: Game = field(default_factory=Game)
    prev_bird_y: float = 5.0
    tick_at: float = 0.0
    tick_seconds: float = 0.25
    p_flap: float = 0.0
    latency_ms: float = 0.0
    calls: int = 0
    cost_usd: float = 0.0
    scores: list[int] = field(default_factory=list[int])
    status: str = ''
    ended: str = ''

    def begin_round(self, round_no: int, playbook: Playbook, game: Game, tick_seconds: float) -> None:
        self.round_no, self.playbook, self.game, self.tick_seconds = round_no, playbook, game, tick_seconds
        self.prev_bird_y, self.tick_at, self.p_flap, self.latency_ms, self.ended = (
            game.bird_y,
            time.perf_counter(),
            0.0,
            0.0,
            '',
        )

    def ticked(self, prev_bird_y: float, decision: Decision) -> None:
        now = time.perf_counter()
        self.tick_seconds = max(self.tick_seconds * 0.7 + (now - self.tick_at) * 0.3, 0.05)  # follow the real cadence
        self.prev_bird_y, self.tick_at = prev_bird_y, now
        self.p_flap, self.latency_ms = decision.p_flap, decision.latency_ms
        self.calls += 1
        self.cost_usd += decision.cost_usd

    def render(self) -> Panel:
        g = self.game
        alpha = min(1.0, (time.perf_counter() - self.tick_at) / self.tick_seconds) if not self.ended else 1.0
        bird_y = self.prev_bird_y + (g.bird_y - self.prev_bird_y) * alpha
        board = g.render(bird_y=bird_y, shift=1.0 - alpha)
        if self.ended:
            board.append(f'\n\n {self.ended}', style='bold')

        side = Table.grid(padding=(0, 1))
        side.add_column(style='dim', no_wrap=True)
        side.add_column()
        hot = 'red' if self.p_flap >= 0.5 else 'cyan'
        side.add_row('flap?', Text(f'{bar(self.p_flap)} {self.p_flap:.2f}', style=hot))
        side.add_row('latency', f'{self.latency_ms:.0f} ms')
        side.add_row('decisions', f'{self.calls}  (${self.cost_usd:.5f} so far)')
        side.add_row('', '')
        side.add_row('playbook', Text(self.playbook.pretty(), style='italic'))
        side.add_row('', '')
        rounds = '  '.join(f'r{i + 1}: {s}' for i, s in enumerate(self.scores)) or 'none yet'
        side.add_row('rounds', rounds)

        body = Table.grid(padding=(0, 2))
        body.add_column(no_wrap=True, min_width=WIDTH)
        body.add_column(width=32)
        body.add_row(board, side)

        title = f' round {self.round_no}   score {g.score}   {self.pilot} plays, {self.coach} coaches '
        return Panel(body, title=title, subtitle=self.status, subtitle_align='left', border_style='blue')


def bar(p: float, width: int = 12) -> str:
    filled = int(round(p * width))
    return '▓' * filled + '░' * (width - filled)


async def play_round(
    game: Game,
    player: Player,
    playbook: Playbook,
    view: View,
    *,
    round_no: int,
    tick_seconds: float,
    win: int,
    pace: bool,
) -> RoundResult:
    replay: list[Tick] = []
    calls = 0
    cost = 0.0
    latency_total = 0.0
    view.begin_round(round_no, playbook, game, tick_seconds)
    with logfire.span('round {round_no} ({pilot})', round_no=round_no, pilot=player.name):
        while not game.dead:
            state = game.state()
            t0 = time.perf_counter()
            decision = await player.decide(state, playbook)
            calls += 1
            cost += decision.cost_usd
            latency_total += decision.latency_ms
            replay.append(Tick(frame=game.frame, state=state, flap=decision.flap, p_flap=decision.p_flap))
            prev_y = game.bird_y
            game.step(decision.flap)
            if game.score >= win and not game.dead:
                game.dead = f'cleared {win} pipes, that is a win'
            view.ticked(prev_y, decision)
            remaining = tick_seconds - (time.perf_counter() - t0)
            if pace and remaining > 0:
                await asyncio.sleep(remaining)
    if pace:
        await asyncio.sleep(tick_seconds)  # let the last interpolated frame land
    view.ended = f'{"🏆" if game.score >= win else "💥"} {game.dead}'
    return RoundResult(
        score=game.score,
        frames=game.frame,
        death=game.dead or 'survived',
        replay=replay,
        pilot_calls=calls,
        pilot_cost_usd=cost,
        pilot_latency_ms=latency_total / max(calls, 1),
    )


async def countdown(view: View, seconds: int, prefix: str) -> None:
    for n in range(seconds, 0, -1):
        view.status = f' {prefix} starting in {n}... '
        await asyncio.sleep(1)
    view.status = ''


async def demo() -> None:
    parser = argparse.ArgumentParser(description='Claude coaches, Jev plays Flappy Bird.')
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--player', choices=['jev', 'claude', 'fake'], default='jev')
    parser.add_argument('--coach', default=os.environ.get('COACH_MODEL', 'anthropic:claude-sonnet-5'))
    parser.add_argument('--offline', action='store_true', help='fake pilot + canned coach, no API keys needed')
    parser.add_argument('--seed', type=int, default=7, help='same pipes every round, so rounds are comparable')
    parser.add_argument('--tps', type=float, default=3.0, help='game ticks per second; one Jev decision per tick')
    parser.add_argument('--win', type=int, default=10, help='stop a round after this many pipes')
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
        player = {
            'jev': lambda: JevPlayer(),
            'claude': lambda: ClaudePlayer(args.coach),
            'fake': lambda: FakePlayer(args.seed),
        }[args.player]()
        coach = make_coach(args.coach)

    tick_seconds = 1 / args.tps
    playbook = STARTER
    results: list[RoundResult] = []
    playbooks: list[Playbook] = []
    history: list[ModelMessage] = []
    coach_cost = 0.0
    view = View(pilot=player.name, coach=args.coach if not args.offline else 'canned coach')

    live = Live(get_renderable=view.render, console=console, refresh_per_second=RENDER_FPS, transient=True)
    if not args.quiet:
        live.start()
    try:
        with logfire.span('flappy demo: {pilot} pilots, coach={coach}', pilot=player.name, coach=args.coach):
            if hasattr(player, 'warmup'):
                view.status = f' warming up {player.name}... '
                await player.warmup(playbook)  # type: ignore[attr-defined]
            for round_no in range(1, args.rounds + 1):
                playbooks.append(playbook)
                game = Game(seed=args.seed)
                view.begin_round(round_no, playbook, game, tick_seconds)
                if not args.quiet:
                    await countdown(view, 3, f'round {round_no}:')
                result = await play_round(
                    game,
                    player,
                    playbook,
                    view,
                    round_no=round_no,
                    tick_seconds=tick_seconds,
                    win=args.win,
                    pace=not args.quiet,
                )
                results.append(result)
                view.scores.append(result.score)
                if args.quiet:
                    print(f' round {round_no}: score {result.score}, {result.death}. {result.pilot_calls} decisions')

                if round_no == args.rounds:
                    break
                view.status = f' {args.coach if not args.offline else "coach"} is reading the replay... '
                prompt = (
                    f'Round {round_no} with this playbook:\n{playbook.pretty()}\n\n'
                    f'Result: {result.summary()}\n\nWrite the playbook for round {round_no + 1}.'
                )
                run = await coach.run(prompt, message_history=history)
                history = run.all_messages()
                playbook = run.output
                coach_cost += float(run.usage.cost or 0)
                view.playbook = playbook
                view.status = f' coach: {playbook.note} '
                if not args.quiet:
                    await asyncio.sleep(4)
    finally:
        if not args.quiet:
            live.stop()

    table = Table(title=f'{player.name} plays, {args.coach} coaches', title_style='bold')
    for col in ('round', 'score', 'how it ended', f'{player.name} decisions', 'avg latency', 'cost'):
        table.add_column(col, justify='right' if col in ('round', 'score', 'avg latency', 'cost') else 'left')
    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            str(r.score),
            r.death,
            str(r.pilot_calls),
            f'{r.pilot_latency_ms:.0f} ms',
            f'${r.pilot_cost_usd:.5f}',
        )
    console.print(table)
    total_calls = sum(r.pilot_calls for r in results)
    total_cost = sum(r.pilot_cost_usd for r in results)
    console.print(f' {player.name}: {total_calls} decisions for ${total_cost:.5f}.  coach: ${coach_cost:.4f}\n')
    console.print(' the playbooks, in order:', style='bold')
    for i, pb in enumerate(playbooks, 1):
        body = Text('   ' + pb.pretty().replace('\n', '\n   '))
        console.print(Group(Text(f' round {i}', style='bold'), body, Text(f'   ({pb.note})', style='dim')))


if __name__ == '__main__':
    try:
        asyncio.run(demo())
    except KeyboardInterrupt:
        pass
