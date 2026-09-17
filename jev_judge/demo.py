# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic-evals>=2", "pydantic-ai-slim[anthropic]>=2", "typesafe-sdk>=0.6", "rich"]
# ///
"""Grade ten support-bot replies with JevJudge and check its verdicts against our own labels.

export TYPESAFE_API_KEY=...
uv run demo.py
uv run demo.py --compare     # also grade with Claude through Pydantic Evals' LLMJudge (needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Callable

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, LLMJudge
from rich import print
from rich.table import Table
from typing_extensions import TypedDict

from jev_judge import JevJudge

POLICY = (
    'Returns are accepted within 30 days if the bike is in its original condition. '
    'Shipping is free within the UK and to Canada, and takes 5 to 7 days. '
    'There is no student discount. Repairs are booked as a slot at the workshop.'
)

RUBRIC = (
    f'The reply is polite, answers what the customer asked, and does not contradict the shop policy. Policy: {POLICY}'
)


class Label(TypedDict):
    should_pass: bool
    why: str


# (case name, customer question, the bot's reply, our own label). Every question is worded differently
# so the fake bot below can look its reply up by question.
REPLIES: list[tuple[str, str, str, Label]] = [
    (
        'return-ok',
        'Can I still return a bike I bought 20 days ago?',
        'Yes. Returns are accepted within 30 days as long as the bike is in its original condition. '
        'Reply with your order number and I will send you a label.',
        {'should_pass': True, 'why': 'correct and helpful'},
    ),
    (
        'return-invented',
        'I bought a bike three weeks ago. Is it too late to return it?',
        'Unfortunately our return window is 14 days, so this order is no longer eligible.',
        {'should_pass': False, 'why': 'invents a 14 day window'},
    ),
    (
        'return-curt',
        'How long do I have to return a bike?',
        '30 days.',
        {'should_pass': False, 'why': 'correct fact, but barely a reply'},
    ),
    (
        'shipping-ok',
        'Do you ship to Canada, and how long does it take?',
        'We do. Shipping to Canada is free and usually takes 5 to 7 days.',
        {'should_pass': True, 'why': 'correct and helpful'},
    ),
    (
        'shipping-rude',
        'Can you deliver to Toronto? How many days?',
        'It is on the FAQ page. Please check there before messaging us.',
        {'should_pass': False, 'why': 'rude and does not answer'},
    ),
    (
        'shipping-wrong-days',
        'I live in Vancouver. Will you ship to me and how long will it take?',
        'We ship to Canada for free. It takes about two weeks.',
        {'should_pass': False, 'why': 'polite, but two weeks contradicts the policy'},
    ),
    (
        'discount-invented',
        'Is there a student discount?',
        'Yes, students get 20% off with a valid ID.',
        {'should_pass': False, 'why': 'invents a discount'},
    ),
    (
        'discount-ok',
        'I am a student. Do you do any discount for that?',
        'Sorry, we do not offer a student discount at the moment. The sale section is worth a look though.',
        {'should_pass': True, 'why': 'correct and polite'},
    ),
    (
        'brakes-ok',
        'My brakes squeak after riding in the rain. What should I do?',
        'Squeaking after rain is usually water or grit on the pads. Wipe the rim and pads with a clean cloth and '
        'do a few gentle stops to dry them. If it keeps up, book a slot at our workshop and we will take a look.',
        {'should_pass': True, 'why': 'helpful, and the workshop detail matches policy'},
    ),
    (
        'brakes-offtopic',
        'The brakes on my new bike squeal whenever it is wet. Any advice?',
        'Thanks for reaching out! Have you seen our new range of helmets? They are 15% off this week.',
        {'should_pass': False, 'why': 'ignores the question'},
    ),
]


def support_bot(question: str) -> str:
    """Stands in for the agent under test, so the demo needs no LLM key. Swap in `agent.run` to grade a real one."""
    return next(reply for _, q, reply, _ in REPLIES if q == question)


class Metered(WrapperModel):
    """Adds up what the model inside costs, so Claude's bill can sit next to Jev's."""

    spent_usd = 0.0

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        response = await super().request(messages, model_settings, model_request_parameters)
        self.spent_usd += float(response.cost().total_price)
        return response


async def demo(compare: bool) -> None:
    cases = [Case(name=name, inputs=question, metadata=label) for name, question, _, label in REPLIES]

    jev = JevJudge(rubric=RUBRIC, include_input=True)
    judges: list[tuple[Evaluator[str, str, Label], Callable[[], float]]] = [(jev, lambda: jev.spent_usd)]
    if compare:
        claude = Metered('anthropic:claude-sonnet-5')
        judges.append((LLMJudge(rubric=RUBRIC, include_input=True, model=claude), lambda: claude.spent_usd))

    summary = Table('Judge', 'Agreed with our labels', 'Per case', 'Cost for 10 cases')
    for judge, spent in judges:
        dataset = Dataset[str, str, Label](name='support-bot replies', cases=cases, evaluators=[judge])
        t0 = time.perf_counter()
        report = await dataset.evaluate(
            support_bot, max_concurrency=1, progress=False
        )  # one at a time, so time is per case
        seconds = time.perf_counter() - t0
        report.print(include_input=True, include_output=True, include_reasons=True, include_durations=False)

        name = next(iter(report.cases[0].assertions))
        agreed = sum(
            c.metadata is not None and c.assertions[name].value == c.metadata['should_pass'] for c in report.cases
        )
        summary.add_row(name, f'{agreed} of {len(cases)}', f'{seconds / len(cases):.2f} s', f'${spent():.5f}')
    print(summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--compare', action='store_true', help='also grade with Claude via LLMJudge')
    args = parser.parse_args()
    for key in ['TYPESAFE_API_KEY'] + (['ANTHROPIC_API_KEY'] if args.compare else []):
        if not os.environ.get(key):
            sys.exit(f'Set {key} first.')
    asyncio.run(demo(args.compare))
