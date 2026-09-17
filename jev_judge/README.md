# Jev as a judge

Grade your evals with Jev instead of an LLM. One call per case. Cheap. Fast.

## Use it

`jev_judge.py` is the whole thing. About 50 lines. Drop it in where you would use `LLMJudge`:

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

Each case gets a pass or fail. Jev's probability is in the reason column.

- `include_input` and `include_expected_output` work like they do on `LLMJudge`.
- `threshold` is 0.5. Raise it to be stricter.
- `judge.spent_usd` is what Jev cost so far.

## Run it

```bash
git clone https://github.com/adtyavrdhn/pydantic-jev-examples && cd pydantic-jev-examples/jev_judge
export TYPESAFE_API_KEY=...
uv run demo.py
uv run demo.py --compare   # Claude Sonnet 5 judges too, needs ANTHROPIC_API_KEY
```

Ten replies from a made-up bike shop bot. One rubric: polite, answers the question, matches the
shop policy. Each reply is hand-labelled. At the end you see how often each judge agreed with
the labels, how long each took per case, and what each cost. Only the TypeSafe key is needed.

Three replies are close calls on purpose. A correct fact said curtly. A polite answer with the
wrong delivery time. A cheerful reply that ignores the question.

## What I saw

Very small set. Probably naive. Ten replies I labelled myself for a side project. I will be
trying this out across our evals suite slowly. This was a nice way to reaffirm what we can do
with it.

Cases run one at a time, so the time is per case. The Claude judge is Sonnet 5. That is the
usual pick for grading: cheaper and faster than the big models, and good enough to explain a
verdict.

| Judge | Agreed with my labels | Per case | Cost for 10 cases |
|---|---|---|---|
| Jev | 9 of 10 | 0.44 s | $0.00018 |
| Claude Sonnet 5 (LLMJudge) | 10 of 10 | 2.16 s | $0.036 |

Jev was sure on nine. Fails scored 0.17 or lower. Passes scored 0.95 or higher.

The miss was the curt reply, "30 days." I labelled it a fail for being brusque. Jev gave it 0.71
and passed it. Its least confident call of the run. Claude failed it and said why. A threshold of
0.75 would have failed it too.

Jev gives you a number for a fraction of a cent. Claude gives you a reason.

## How it works

Pydantic Evals calls `evaluate` once per case. The judge puts the output, and the input and
expected output if you asked for them, into Jev's state. It asks one question: does the output
satisfy the rubric? Jev returns a probability. At or above the threshold, pass.

Jev never writes a reason. You get a number. Close calls show up as numbers near the threshold.

## Files

| File | What it is |
|---|---|
| `jev_judge.py` | the judge |
| `demo.py` | ten labelled replies, graded |
