# /// script
# requires-python = ">=3.12"
# dependencies = ["typesafe-sdk>=0.6", "rich"]
# ///
"""Can Jev follow a flap rule? Ask it about eight hand-picked situations, three ways.

    TYPESAFE_API_KEY=... uv run probe.py

Each row is a situation where the right answer is obvious. Each column is a way of describing
it to Jev: the raw numbers the demo sends today, the numbers plus a sentence, and the sentence
alone. A column "works" if its probabilities are high where the answer is FLAP and low where
it is WAIT. That tells us how to feed Jev, or that Jev is the wrong pilot.
"""

from __future__ import annotations

import asyncio
import time

from rich.console import Console
from rich.table import Table
from typesafe_sdk import AsyncTypeSafeClient, JSONContent, Noul, NoulAnswer

PHYSICS = (
    'bird_y is the bird height: 0 is the top of the screen, 11 is the ground. '
    'Each tick the bird falls a bit faster (velocity grows by 0.35). '
    'A flap sets velocity to -1.1 (up): one flap lifts the bird about 1.2 rows, peaking 3 ticks later, '
    'then it falls again. Positive velocity means falling. '
    'The next pipe is distance_to_pipe columns away and moves 1 column closer each tick. '
    'When distance_to_pipe is 0 or 1 the bird must be between gap_top and gap_bottom or it dies. '
    'Hitting the ground also kills it.'
)

PLAYBOOK = (
    'Aim for the centre of the gap. When the bird is below the centre of the gap and not already rising, flap. '
    'When the bird is above the centre of the gap, wait. When the bird is falling fast (velocity above 1.0) '
    'and at or below the centre, flap. Never flap while the bird is above the top of the gap.'
)

# (bird_y, velocity, gap_top, gap_bottom, distance, expected)
SITUATIONS = [
    (9.5, 1.4, 3, 8, 4, 'FLAP'),  # way below the gap, falling fast
    (7.0, 0.6, 3, 8, 6, 'FLAP'),  # below centre, falling
    (6.0, 0.1, 3, 8, 10, 'FLAP'),  # just below centre, drifting down
    (6.0, -0.9, 3, 8, 10, 'WAIT'),  # just below centre but already rising
    (5.0, 0.3, 3, 8, 8, 'WAIT'),  # at centre, gently falling: let it fall a bit
    (3.5, 0.2, 3, 8, 5, 'WAIT'),  # above centre
    (1.5, -0.5, 3, 8, 3, 'WAIT'),  # above the gap entirely, rising
    (2.0, 1.2, 6, 11, 2, 'WAIT'),  # high up, gap is low: must fall
]


def sentence(y: float, v: float, top: int, bottom: int, d: int) -> str:
    centre = (top + bottom) / 2 - 0.5
    off = y - centre
    if abs(off) < 0.3:
        where = 'at the centre of the gap'
    else:
        where = f'{abs(off):.1f} rows {"below" if off > 0 else "above"} the centre of the gap'
    motion = 'rising' if v < -0.2 else 'falling fast' if v > 1.0 else 'falling' if v > 0.2 else 'hovering'
    above_gap = ' and above the top of the gap' if y < top else ''
    return f'The bird is {where}{above_gap}, {motion} (velocity {v:+.1f}), and the pipe is {d} columns away.'


async def ask(client: AsyncTypeSafeClient, state: JSONContent) -> tuple[float, float]:
    q = Noul(
        instructions={
            'question': 'Should the bird flap on this tick?',
            'how_the_game_works': PHYSICS,
            'playbook': PLAYBOOK,
        },
        criteria={
            'true': 'Flap now: the bird needs to go up to survive.',
            'false': 'Do not flap: let the bird fall this tick.',
        },
    )
    t0 = time.perf_counter()
    r = await client.system_one(state=state, questions={'flap': q})
    a = r.answers['flap']
    assert isinstance(a, NoulAnswer)
    return a.noul, (time.perf_counter() - t0) * 1000


async def main() -> None:
    console = Console()
    table = Table(title='p(flap) per situation, three ways of describing it', title_style='bold')
    for col in ('situation', 'expect', 'numbers', 'numbers+sentence', 'sentence only'):
        table.add_column(col, justify='left' if col == 'situation' else 'center')
    latencies: list[float] = []
    async with AsyncTypeSafeClient() as client:
        for y, v, top, bottom, d, expect in SITUATIONS:
            numbers = {
                'bird_y': y,
                'velocity': v,
                'gap_top': top,
                'gap_bottom': bottom,
                'distance_to_pipe': d,
                'score': 0,
            }
            text = sentence(y, v, top, bottom, d)
            cells: list[str] = []
            for state in (numbers, {**numbers, 'situation': text}, text):
                p, ms = await ask(client, state)
                latencies.append(ms)
                right = (p >= 0.5) == (expect == 'FLAP')
                cells.append(f'[{"green" if right else "red"}]{p:.2f}[/]')
            table.add_row(f'y={y} v={v:+.1f} gap {top}-{bottom} d={d}', expect, *cells)
    console.print(table)
    avg = sum(latencies) / len(latencies)
    console.print(f' green = agrees with the expected answer.  avg latency {avg:.0f} ms over {len(latencies)} calls')


if __name__ == '__main__':
    asyncio.run(main())
