---
name: A published number looks wrong
about: The most welcome kind of issue
title: "[number] "
labels: correctness
---

**Which number, and where.** File and line, please.

**What you think it should be, and how you got there.** If you recomputed it
from a replay bundle, paste the command — that is the fastest possible path to
agreement:

```bash
python scripts/verify_replay_bundle.py \
  --bundle   results_archive/replay/<bundle> \
  --manifest results_archive/gold/<run>/manifest.json
```

**Anything else.** Several published figures here have been wrong, and every one
was found by someone checking rather than by the tests. This project's own
history is the argument for filing this issue.
