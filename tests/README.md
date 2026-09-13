# Handler unit tests

These cover the part of a Function that is **pure decision**: which rung resolved a
file, whether a human's veto is honoured, what gets retracted, how a score is banded,
and whether the quality gate can actually fail.

They do not test that CDF behaves as documented — only a live run does that, and
`tools/live_e2e.py` is what does it. What they do is reach the cases a live run reaches
only by contrivance. Getting a real project into the middle confidence band, or into
"a rule was deleted and the link must come back off", means editing data in CDF and
waiting minutes per attempt. Here it is a dictionary and a millisecond.

```bash
uv run --group dev python -m pytest tests/ -q
```

The fakes live in `conftest.py` and are deliberately thin — just enough of `client.raw`
and `client.data_modeling.instances` for the logic under test. A fake that grows to
mimic the whole SDK stops being a test aid and becomes a second implementation to
maintain, with its own bugs and no users.
