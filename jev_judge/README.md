# Jev as a judge

I decided to play with using Jev as an evaluator. It makes one call per case, and each call is
fast and costs almost nothing. Playing with it is fun and here is what we did.

## Use it

Everything is in `jev_judge.py`, about 50 lines. It is a normal
[Pydantic Evals](https://ai.pydantic.dev/evals/) evaluator, so it plugs in the same way
`LLMJudge` does:

```python
from pydantic_evals import Dataset
from jev_judge import JevJudge

dataset = Dataset(
    name='support replies',
    cases=[...],
    evaluators=[JevJudge(rubric='The reply is polite and answers the question.', include_input=True)],
)
report = await dataset.evaluate(my_task)
report.print()
```

Each case comes back as a pass or a fail, and Jev's probability shows up in the reason column.

- `include_input` and `include_expected_output` do the same thing they do on `LLMJudge`.
- `threshold` defaults to 0.5. Raise it if you want the judge to be stricter.
- `judge.spent_usd` tells you what Jev has cost so far.

## Run it

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/jev_judge
export TYPESAFE_API_KEY=...
uv run demo.py
uv run demo.py --compare   # Claude Sonnet 5 grades the same cases, needs ANTHROPIC_API_KEY
```

The demo has ten replies from a made-up bike shop support bot. There is one rubric: the reply
should be polite, answer the question, and match the shop's policy. I labelled each reply pass
or fail by hand. When it finishes you see how often each judge agreed with my labels, how long
each one took per case, and what each one cost. You only need the TypeSafe key unless you add
`--compare`.

Three of the replies are close calls on purpose: a correct answer given curtly, a polite answer
with the wrong delivery time, and a cheerful reply that never answers the question.

## What I saw

This is a very small set, and probably a naive one. It is ten replies I labelled myself for a
side project, so take it for what it is. I will be trying this out across our evals suite
slowly, but it was a nice way to reaffirm what we can do with it.

The cases run one at a time, so the times below are per case. The Claude judge is Sonnet 5,
which is what people usually use for grading since it is cheaper and faster than the big models
and still explains its verdicts well.

| Judge | Agreed with my labels | Per case | Cost for 10 cases |
|---|---|---|---|
| Jev | 9 of 10 | 0.44 s | $0.00018 |
| Claude Sonnet 5 (LLMJudge) | 10 of 10 | 2.16 s | $0.036 |

Jev was confident on nine of the ten. Every fail scored 0.17 or lower and every pass scored
0.95 or higher.

The one it got wrong was the curt reply, where the bot just said "30 days." I had marked that
as a fail because it is brusque. Jev gave it 0.71 and passed it, which was its least confident
answer of the whole run. Claude failed it and explained that it was correct but not polite. If
I had set the threshold to 0.75, Jev would have failed it too.

So Jev gives you a number for a fraction of a cent, and Claude gives you a reason.

## What you lose

Pydantic Evals' `LLMJudge` is a yes or no evaluator at heart, but it also asks the model for a
sentence saying why, and that sentence ends up in the report. Jev gives you the same pass or
fail without the sentence. You get a probability instead.

For finding the cases worth a look, the probability does most of that job, since the close
calls sit near the threshold. If you want prose on those cases, run an LLM judge on just the
fails and close calls. And if you want to know which part of the rubric failed, split the
rubric into checks and ask Jev one yes or no per check. None of that is built here. This folder
is the plain version, one question per case.

## How it works

Pydantic Evals calls `evaluate` once per case. The judge puts the output into Jev's state,
along with the input and expected output if you asked for them, and asks one question: does
this output satisfy the rubric? Jev answers with a probability. If it is at or above the
threshold, the case passes.

Jev never writes a reason. You just get a number, so the close calls show up as numbers near
the threshold.

## Files

| File | What it is |
|---|---|
| `jev_judge.py` | the judge |
| `demo.py` | ten labelled replies, graded |
