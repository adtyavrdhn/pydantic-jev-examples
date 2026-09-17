"""The game itself: a tiny Flappy Bird with no AI in it.

Nothing here talks to Jev or to Claude. `BirdState.describe()` turns the numbers into one
sentence, and `Playbook` is what the coach writes and the pilot reads.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from rich.text import Text
from typesafe_sdk import NoulCriteria

WIDTH = 40
HEIGHT = 12  # rows 0..11; row 11 is the ground
BIRD_X = 8
GRAVITY = 0.35
FLAP_VELOCITY = -1.1
GAP = 5
PIPE_EVERY = 14
PIPE_WIDTH = 2

PHYSICS = (
    'Gravity pulls the bird down a little faster every tick. One flap lifts it about 1.2 rows, peaking 3 ticks '
    'later, then it falls again; flapping on consecutive ticks keeps lifting. The pipe moves 1 column closer '
    f'each tick. To survive, the bird must be inside the gap ({GAP} rows tall) when the pipe arrives. '
    'Hitting the ground or the screen top edge is also fatal.'
)

VOCABULARY = (
    'Every situation is described with these phrases only. Position: "N rows below the centre of the gap", '
    '"N rows above the centre of the gap", or "at the centre of the gap", plus "and above the top of the gap" or '
    '"and below the bottom of the gap" when outside it. Motion: "rising", "hovering", "falling", or '
    '"falling fast". Pipe: "the pipe is N columns away" or "the bird is inside the pipe".'
)


class BirdState(BaseModel):
    """What the pilot sees on every tick."""

    bird_y: float = Field(description=f'Bird height. 0 is the top, {HEIGHT - 1} is the ground.')
    velocity: float = Field(description='Positive means falling, negative means rising.')
    gap_top: int = Field(description='First open row of the next pipe gap.')
    gap_bottom: int = Field(description='First blocked row below the gap.')
    distance_to_pipe: int = Field(description='Columns until the next pipe. 0 means inside it.')
    score: int

    def describe(self) -> str:
        """The situation in words, using VOCABULARY. This is what Jev reads; it does not do arithmetic."""
        centre = (self.gap_top + self.gap_bottom) / 2 - 0.5
        off = self.bird_y - centre
        if abs(off) < 0.3:
            where = 'at the centre of the gap'
        else:
            where = f'{abs(off):.1f} rows {"below" if off > 0 else "above"} the centre of the gap'
        if self.bird_y < self.gap_top - 0.5:
            where += ' and above the top of the gap'
        elif self.bird_y > self.gap_bottom - 0.5:
            where += ' and below the bottom of the gap'
        v = self.velocity
        motion = 'rising' if v < -0.2 else 'falling fast' if v > 1.0 else 'falling' if v > 0.2 else 'hovering'
        inside = self.distance_to_pipe <= 1
        pipe = 'the bird is inside the pipe' if inside else f'the pipe is {self.distance_to_pipe} columns away'
        return f'The bird is {where}, {motion}, and {pipe}.'


class Playbook(BaseModel):
    """The yes and no criteria of the question Jev answers every tick. Short on purpose: Jev is billed per input token."""

    flap_when: list[str] = Field(min_length=1, max_length=4, description='Situations in which the bird should flap.')
    wait_when: list[str] = Field(
        min_length=1, max_length=4, description='Situations in which the bird should not flap.'
    )
    note: str = Field(max_length=200, description='One line: what changed since the last round and why.')

    def criteria(self) -> NoulCriteria:
        return {'true': 'Flap now. ' + ' '.join(self.flap_when), 'false': 'Do not flap. ' + ' '.join(self.wait_when)}

    def pretty(self) -> str:
        return 'flap when: ' + '; '.join(self.flap_when) + '\nwait when: ' + '; '.join(self.wait_when)


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
            lines.append(f'  {t.state.describe()} -> {"FLAP" if t.flap else "wait"} (p={t.p_flap:.2f})')
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
    pipes: list[Pipe] = field(default_factory=list[Pipe])
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

    def render(self, bird_y: float | None = None, shift: float = 0.0) -> Text:
        """Draw the board. `bird_y` and `shift` let the caller interpolate between ticks."""
        y_draw = self.bird_y if bird_y is None else bird_y
        grid = [[' '] * WIDTH for _ in range(HEIGHT)]
        for p in self.pipes:
            for dx in range(PIPE_WIDTH):
                x = int(p.x + shift + 0.5) + dx
                if 0 <= x < WIDTH:
                    for y in range(HEIGHT - 1):
                        if not (p.gap_top <= y < p.gap_bottom):
                            grid[y][x] = '█'
        row = min(HEIGHT - 1, max(0, int(y_draw + 0.5)))
        grid[row][BIRD_X] = '@'
        text = Text()
        for y, r in enumerate(grid):
            for ch in r:
                text.append(ch, style='green' if ch == '█' else 'bold yellow' if ch == '@' else '')
            text.append('\n')
        text.append('▔' * WIDTH, style='dim')
        return text
