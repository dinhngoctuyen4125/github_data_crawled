# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Replication package for *LLMs Meet Library Evolution: Evaluating Deprecated API Usage in LLM-based Code Completion*
(145 deprecated→replacement API mappings over numpy, pandas, scikit-learn, scipy, seaborn, tensorflow, pytorch,
transformers). Two parts:

- **Original study** (`llm_dep/data_collection`, `probing`, `fixing`): build line-completion prompts from functions
  that call an *outdated* (O) or *up-to-dated* (U) API, run LLMs on them, and evaluate mitigations
  (`fixing/replacing.py` = ReplaceAPI, `fixing/prompting.py` = InsertPrompt). Scripts take `--model`, `--lib`, `--maxlen`.
- **Dataset extension** (`llm_dep/crawling`): crawl GitHub / Sourcegraph for more O/U samples, version-aware. This is
  where current work happens.

## Environment

- Use **Python 3.11 or 3.12**. Python 3.13 removed `lib2to3`, which `crawling/extract.py` needs to read Python 2
  files (it only logs a warning and yields no samples for them). Python < 3.11 lacks `tomllib` (used by `deps.py`).
  On this machine: `C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe` (conda base is 3.13).
- Tokens `GITHUB_TOKEN`, `SRC_ACCESS_TOKEN` live in `.env` (gitignored, template `.env.example`). Never print them.
  Verify with `python -m llm_dep.crawling.check`.
- No test suite. Regression check for the signature logic: `python -m llm_dep.crawling.selfcheck`
  (recomputes `versions` of existing O/U samples).

## Crawling commands

Run from the repo root, **one command at a time** (they share a token and rate limits):

```
python -m llm_dep.crawling.run --libs numpy --plan                       # print per-cell deficits only
python -m llm_dep.crawling.run --libs numpy                              # Sourcegraph, assign by dependency
python -m llm_dep.crawling.run --libs numpy --assign signature --cached-only --reprocess   # re-read cached files
python -m llm_dep.crawling.run --libs numpy --source github --assign signature --search-limit 5000 --wait-on-block 30
python -m llm_dep.crawling.report --export                               # AFTER.md + data/<lib>/{O,U}_crawled.json
```

`run_others.ps1` holds the current batch of commands for the non-pytorch/tensorflow libraries (those two are crawled
on other machines; see `llm_dep/crawling/README.md`, written in Vietnamese for those collaborators).
Lib-specific flags: pandas `--infer-types`, transformers `--allow-from-pretrained`, tensorflow `--cap 500`.
Interrupted runs resume when the same command is re-run.

## Crawling architecture

Pipeline (see `crawling/__init__.py`, `run.py` docstring): search code → download file at a fixed commit → extract
call sites → assign library versions → accept the sample only for (mapping, U/O, milestone) cells still short.

- **Inputs**: `data/api_mapping_versions.json`, `data/<lib>/migration_evolution.json` (evolution path: milestones
  and API signatures per milestone), `data/<lib>/{O,U}_modified.json` (original samples; crawled functions that
  duplicate them are skipped), `manual_reviews/API_MIGRATION_COUNTS_BEFORE.md` (baseline counts).
- **Quota** (`quota.py`): a cell's target is the largest count on its evolution path (or `--cap`), minus the BEFORE
  count; cells where the target API does not exist at that milestone are infeasible (quota 0).
- **Search**: `sourcegraph.py` (streaming, can target repos by dependency version) or `github_search.py`
  (REST code search, ≤1000 results/query so queries are bisected by `size:`; ~10 req/min).
- **Extraction** (`extract.py`): `CallSiteMatcher` extends `data_collection/api_matcher.APIMatcher`. It keeps the
  earliest matching call per function so the prompt never contains the target API. It also handles indexers
  (`df.loc[...]`), pandas type inference (`pandas_types.py`), `Cls.from_pretrained`, relative imports inside copies
  of the library (package inferred from the file path), and Python 2 files (lib2to3 syntax fixers only, text mapped
  back 1:1 to original lines).
- **Version assignment** — two branches sharing one `samples.jsonl` and one quota:
  - `--assign dependency`: version from the repo's dependency files at that commit (`deps.py`, `versions.py`,
    `pypi.py` release dates), must fall in `[v1, v2)` of the path, plus a signature check;
  - `--assign signature`: every milestone whose signature the `api_call` binds to (`signature.py`, which parses
    both Python and ATen schema signatures).
- **Outputs** per lib in `data/<lib>/crawl/`: `samples.jsonl` (append-only, deduplicated by function text),
  `processed*.progress.jsonl` (one file per source/assign branch, used for resume), log in `data/crawl.log`,
  HTTP cache in `cache/`. `report.py` trims extras for cells BEFORE already filled unless `--keep-extra`.

Sample records must keep the same key set as the original data (`function`, `probing input`, `reference`,
`alias dict`, ...); don't add per-sample fields.

## Working conventions with this user

- Reply in Vietnamese.
- Explain and get approval before editing code or data files.
- Respect API rate limits; never rotate tokens or run crawls in parallel on the same token.
