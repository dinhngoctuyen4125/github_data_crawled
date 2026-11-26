# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository.

## What this repo is

Replication package for *LLMs Meet Library Evolution: Evaluating Deprecated API Usage in LLM-based Code Completion*
(145 deprecated→replacement API mappings over numpy, pandas, scikit-learn, scipy, seaborn, tensorflow, pytorch,
transformers).

- **Original study** (`llm_dep/data_collection`, `probing`, `fixing`):
  - builds line-completion prompts from functions that call an *outdated* (O) or *up-to-dated* (U) API, and runs LLMs on them;
  - evaluates mitigations: `fixing/replacing.py` = ReplaceAPI, `fixing/prompting.py` = InsertPrompt;
  - scripts take `--model`, `--lib`, `--maxlen`.
- **Dataset extension** (`llm_dep/crawling`): crawls GitHub / Sourcegraph for more O/U samples, version-aware. Current
  work happens here.

## Environment

- **Python 3.11 or 3.12**. On this machine: `C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe`.
  - 3.13 removed `lib2to3`, which `extract.py` needs for Python 2 files (they would yield no samples).
  - < 3.11 lacks `tomllib`, which `deps.py` needs.
  - conda base on this machine is 3.13, so don't use it.
- Tokens `GITHUB_TOKEN`, `SRC_ACCESS_TOKEN` live in `.env` (gitignored, template `.env.example`).
  - Never print them.
  - Check them with `python -m llm_dep.crawling.check`.
- There is no test suite. Regression checks to run after a change:
  - `python -m llm_dep.crawling.selfcheck` must give `agree=27133 disagree=0 undecidable=294`;
  - `python -m llm_dep.crawling.selfcheck --lenient-starred` must give `agree=27427 disagree=0 undecidable=0`.

## Crawling commands

Run from the repo root, **one command at a time**: they share one token and its rate limits.

```bash
python -m llm_dep.crawling.run --libs numpy --plan                       # print per-cell deficits only
python -m llm_dep.crawling.run --libs numpy                              # #1 Sourcegraph, assign by dependency
python -m llm_dep.crawling.run --libs numpy --assign signature --search-limit 5000              # #2 Sourcegraph, by signature
python -m llm_dep.crawling.run --libs numpy --source github --assign signature --search-limit 5000 --wait-on-block 30   # #3 GitHub
python -m llm_dep.crawling.run --libs numpy --assign signature --cached-only --reprocess        # re-read cached files only
python -m llm_dep.crawling.report --export                               # NEED.md + AFTER.md + data/<lib>/{O,U}_crawled.json
```

- `run_others.ps1` holds the current batch.
  - The user runs it; Claude only edits its commands.
  - pytorch and tensorflow are also crawled on other machines (`llm_dep/crawling/README.md`, in Vietnamese).
- Library-specific flags: pandas `--infer-types`, transformers `--allow-from-pretrained`, tensorflow `--cap 500`.
- `--min-target N` raises every target to at least N (currently 50).
  - `report` must get the same `--min-target`; otherwise it trims the samples above the old target.
- Other useful flags: `--notebooks` (search `.ipynb`), `--wait-on-block`, `--gh-interval`, `--kinds`.
- Re-running an interrupted command resumes it.
- Search results are cached per query string **and** `--search-limit`.
  - Sourcegraph caches were made with 2000 (command #1 default) and 5000 (#2).
  - GitHub caches each result page regardless of the limit.
  - A `--cached-only` re-read must therefore reuse those limits.

## Crawling architecture

Flow (`run.py`): search code → download the file at a fixed commit → extract call sites → assign library versions →
accept the sample only for (mapping, U/O, milestone) cells still short.

- **Inputs**:
  - `data/api_mapping_versions.json`;
  - `data/<lib>/migration_evolution.json`: milestones and API signatures per milestone;
  - `data/<lib>/{O,U}_modified.json`: the original samples (crawled functions duplicating them are skipped);
  - `manual_reviews/API_MIGRATION_COUNTS_BEFORE.md`: baseline counts.
- **Quota** (`quota.py`):
  - target of a mapping = max(largest U/O cell of BEFORE, `--min-target`), then at most `--cap`;
  - O and U cells of a mapping share this one target;
  - need of a cell = target − BEFORE;
  - cells whose API does not exist at that milestone are infeasible (quota 0).
- **Search**:
  - `sourcegraph.py`: streaming search; it can target repositories by dependency version (`repo:has.file`);
  - `github_search.py`: REST code search, ≤1000 results per query (so queries are bisected by `size:`), ~10 requests/min;
  - query strings are cache keys: changing them invalidates existing caches.
- **Extraction** (`extract.py`): `CallSiteMatcher` extends `data_collection/api_matcher.APIMatcher`.
  - It keeps the earliest matching call per function, so the prompt never contains the target API.
  - A sample is a function/method or a block of up to 5 module-level statements, as in the paper.
  - It also handles:
    - indexers such as `df.loc[...]`;
    - pandas type inference (`pandas_types.py`);
    - `Cls.from_pretrained`;
    - module-level aliases made by assignment (`tf1 = tf.compat.v1`);
    - unbound calls `Cls.method(obj, ...)`;
    - relative imports inside copies of the library;
    - Python 2 files (lib2to3 syntax fixers only, text mapped back 1:1 to the original lines).
- **Parallelism** (`run.py` `_analyze_batch`):
  - downloads and dependency resolution run in threads of the main process, so request intervals hold;
  - call-site extraction is pure CPU work and runs in `--workers` processes;
  - if a worker dies, that file is extracted in the main process and the pool is recreated.
- **Testing offline**: blocking `net.get` alone caches "missing" results in `cache/`; also stub `DiskCache.put`.
- **Notebooks** (`--notebooks`):
  - code cells are joined into one script;
  - IPython magics and cells that do not parse are commented out;
  - `.ipynb_checkpoints/` is skipped;
  - the cache keeps only the code cells.
- **Version assignment**: two branches sharing one `samples.jsonl` and one quota.
  - `--assign dependency` (#1): the version comes from the repo's dependency files at that commit (`deps.py`,
    `versions.py`, `pypi.py`). It must fall in one `[v1, v2)` of the path, and the call must also bind to the signature.
  - `--assign signature` (#2, #3): the sample gets every milestone whose signature the `api_call` binds to
    (`signature.py`, Python argument binding over Python or ATen signatures). Calls with `*args` / `**kwargs` are lenient.
- **Outputs** in `data/<lib>/crawl/`:
  - `samples.jsonl`: append-only, deduplicated by function text;
  - `processed*.progress.jsonl`: one per source/assign branch, used for resume;
  - log in `data/crawl.log`, HTTP cache in `cache/` (tensorflow's in `cache_tensorflow/`).
- **Report** (`report.py`):
  - trims samples of cells already full, unless `--keep-extra`;
  - writes `manual_reviews/API_MIGRATION_COUNTS_NEED.md` (`crawled/needed`);
  - writes `manual_reviews/API_MIGRATION_COUNTS_AFTER.md`: final counts, `-` where the API is absent, the largest
    BEFORE cell next to each pair.
- Sample records keep the key set of the original data (`function`, `probing input`, `reference`, `alias dict`, ...):
  don't add per-sample fields.

## Working conventions with this user

- Reply in Vietnamese, as short bullets that still cover every point.
- Explain and get approval before editing code or data files.
- Respect API rate limits; never rotate tokens or run crawls in parallel on the same token.
- See `HANDOFF.md` for the current state and the decisions taken.
