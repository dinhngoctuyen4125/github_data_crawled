$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# tensorflow on this machine, with the tensorflow machine's cache (cache_tensorflow/: its searches and files).
# New in the code: module aliases by assignment (`tf1 = tf.compat.v1`), the queries `"compat.v1" <name>` (GitHub) /
# `compat.v1 .<name>(` (Sourcegraph), and the `"<module>.<name>"` GitHub query the tensorflow machine lacked.
# data/tensorflow/crawl/samples.jsonl was de-duplicated (backup: samples.jsonl.bak-dup).
# Make sure nothing else is crawling with the same tokens. ONE command at a time.
$tf = @('--libs', 'tensorflow', '--cap', '500', '--assign', 'signature', '--search-limit', '5000', '--cache', 'cache_tensorflow')

# The cached-only reprocess (`--cached-only --reprocess` for #3 and #2) already ran on 2026-11-26; it is not repeated.
# Re-running resumes: finished queries, fetched result pages, downloaded and processed files are skipped.

# 1. New searches: only the new queries are sent, the others are answered from cache_tensorflow.
& $py -m llm_dep.crawling.run @tf --source github --wait-on-block 30 --gh-interval 20   # command #3
& $py -m llm_dep.crawling.run @tf --wait-on-block 60                                     # command #2

# 2. Report
& $py -m llm_dep.crawling.report --export
