"""JevJudge: grade eval cases with Jev instead of an LLM.

    dataset = Dataset(name=..., cases=[...], evaluators=[JevJudge(rubric='The reply is polite and answers the question.')])
    report = await dataset.evaluate(my_task)

One Jev call per case, so a thousand cases cost a few cents and finish in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_core import to_jsonable_python
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext
from typesafe_sdk import AsyncTypeSafeClient, JSONContent, Noul, NoulAnswer

JEV_USD_PER_INPUT_TOKEN = 42 / 1_000_000_000

QUESTION = (
    'Does the output satisfy the rubric? Judge only what the rubric asks for. '
    'If an expected output is given, treat it as the reference answer.'
)


@dataclass
class JevJudge(Evaluator[object, object, object]):
    """Ask Jev one yes/no question per case: does this output satisfy the rubric?"""

    rubric: str
    include_input: bool = False
    include_expected_output: bool = False
    threshold: float = 0.5  # pass at or above this probability
    client: AsyncTypeSafeClient | None = None  # made on first use; reads TYPESAFE_API_KEY

    def __post_init__(self) -> None:
        self.spent_usd = 0.0

    async def evaluate(self, ctx: EvaluatorContext[object, object, object]) -> EvaluationReason:
        state: dict[str, JSONContent] = {'output': to_jsonable_python(ctx.output)}
        if self.include_input:
            state['input'] = to_jsonable_python(ctx.inputs)
        if self.include_expected_output:
            state['expected_output'] = to_jsonable_python(ctx.expected_output)
        question = Noul(instructions={'question': QUESTION, 'rubric': self.rubric})

        self.client = self.client or AsyncTypeSafeClient()
        response = await self.client.system_one(state=state, questions={'pass': question})
        answer = response.answers['pass']
        assert isinstance(answer, NoulAnswer)
        self.spent_usd += (response.usage.input_tokens or 0) * JEV_USD_PER_INPUT_TOKEN

        return EvaluationReason(value=answer.noul >= self.threshold, reason=f'Jev: {answer.noul:.2f} likely to pass')
