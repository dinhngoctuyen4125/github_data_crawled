$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# tensorflow on THIS machine (no tensorflow cache here: every query is searched again, but files already in
# data/tensorflow/crawl/processed*.progress.jsonl are skipped, so only new files are downloaded).
# New in the code: module aliases by assignment (`tf1 = tf.compat.v1`), the query `"compat.v1" <name>`
# (GitHub) / `compat.v1 .<name>(` (Sourcegraph), and the `"<module>.<name>"` query the tensorflow machine lacked.
# Make sure nothing else is crawling tensorflow with the same tokens. ONE command at a time.

# 1. Command #3: GitHub, assign by signature (long, ~10 searches/min).
& $py -m llm_dep.crawling.run --libs tensorflow --cap 500 --source github --assign signature --search-limit 5000 --wait-on-block 30 --gh-interval 20

# 2. Command #2: Sourcegraph, assign by signature.
& $py -m llm_dep.crawling.run --libs tensorflow --cap 500 --assign signature --search-limit 5000 --wait-on-block 60

# 3. Report
& $py -m llm_dep.crawling.report --export
