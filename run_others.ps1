$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# tensorflow, command #3 (GitHub, assign by signature) again, after removing the 1,499 duplicate samples that two
# parallel #3 processes had written (backup: data/tensorflow/crawl/samples.jsonl.bak-dup).
# Run on the tensorflow machine (its cache/ holds the GitHub searches and files), with the latest code and the
# de-duplicated data/tensorflow/crawl/samples.jsonl copied there. ONE command at a time, never two in parallel.

# 1. Re-read the cached searches and files: refills the cells freed by the de-duplication (no search API calls).
& $py -m llm_dep.crawling.run --libs tensorflow --cap 500 --source github --assign signature --search-limit 5000 --cached-only --reprocess

# 2. New GitHub searches: only the queries the old code did not have ("v1.to_double", "saved_model.load", ...);
#    the other queries are answered from the cache.
& $py -m llm_dep.crawling.run --libs tensorflow --cap 500 --source github --assign signature --search-limit 5000 --wait-on-block 30

# 3. Report
& $py -m llm_dep.crawling.report --export
