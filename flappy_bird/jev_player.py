"""Jev at the controls: one yes/no question per game tick.

This is the whole Jev integration. Everything else in the folder is the game and the show.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import logfire
from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulAnswer

from game import PHYSICS, BirdState, Game, Playbook

# https://typesafe.ai: $42 per billion input tokens, output free.
JEV_USD_PER_INPUT_TOKEN = 42 / 1_000_000_000


@dataclass
class Decision:
    flap: bool
    p_flap: float
    latency_ms: float
    cost_usd: float = 0.0


class JevPlayer:
    """One Noul per tick: should the bird flap right now?"""

    name = 'Jev'

    def __init__(self, client: AsyncTypeSafeClient | None = None, *, threshold: float = 0.5):
        self._client = client or AsyncTypeSafeClient()
        self.threshold = threshold

    async def warmup(self, playbook: Playbook) -> None:
        """One throwaway call so the first real tick does not pay for the connection setup."""
        await self.decide(Game().state(), playbook)

    async def decide(self, state: BirdState, playbook: Playbook) -> Decision:
        question = Noul(
            instructions={'question': 'Should the bird flap on this tick?', 'how_the_game_works': PHYSICS},
            criteria=playbook.criteria(),
        )
        situation = state.describe()
        t0 = time.perf_counter()
        with logfire.span('jev flap? {situation}', situation=situation) as span:
            response = await self._client.system_one(state=situation, questions={'flap': question})
            latency_ms = (time.perf_counter() - t0) * 1000
            answer = response.answers['flap']
            assert isinstance(answer, NoulAnswer)
            cost = (response.usage.input_tokens or 0) * JEV_USD_PER_INPUT_TOKEN
            span.set_attributes(
                {'p_flap': answer.noul, 'latency_ms': latency_ms, 'cost_usd': cost, 'model': response.model}
            )
        return Decision(flap=answer.noul >= self.threshold, p_flap=answer.noul, latency_ms=latency_ms, cost_usd=cost)
