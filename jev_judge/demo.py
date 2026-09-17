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

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, LLMJudge
from rich import print
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


async def demo(compare: bool) -> None:
    judge = JevJudge(rubric=RUBRIC, include_input=True)
    evaluators: list[Evaluator[str, str, Label]] = [judge]
    if compare:
        evaluators.append(LLMJudge(rubric=RUBRIC, include_input=True, model='anthropic:claude-fable-5'))

    dataset = Dataset[str, str, Label](
        name='support-bot replies',
        cases=[Case(name=name, inputs=question, metadata=label) for name, question, _, label in REPLIES],
        evaluators=evaluators,
    )
    report = await dataset.evaluate(support_bot, progress=False)
    report.print(include_input=True, include_output=True, include_reasons=True)

    for evaluation_name in report.cases[0].assertions:
        agreed = sum(
            c.metadata is not None and c.assertions[evaluation_name].value == c.metadata['should_pass']
            for c in report.cases
        )
        print(f'[bold]{evaluation_name}[/] agreed with our labels on {agreed} of {len(report.cases)} cases')
    print(f'Jev cost for {len(report.cases)} cases: ${judge.spent_usd:.5f}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--compare', action='store_true', help='also grade with Claude via LLMJudge')
    args = parser.parse_args()
    for key in ['TYPESAFE_API_KEY'] + (['ANTHROPIC_API_KEY'] if args.compare else []):
        if not os.environ.get(key):
            sys.exit(f'Set {key} first.')
    asyncio.run(demo(args.compare))
