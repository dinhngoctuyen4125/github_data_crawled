$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# tensorflow on this machine, with the tensorflow machine's cache (cache_tensorflow/: its searches and files).
# New in the code: module aliases by assignment (`tf1 = tf.compat.v1`), the queries `"compat.v1" <name>` (GitHub) /
# `compat.v1 .<name>(` (Sourcegraph), and the `"<module>.<name>"` GitHub query the tensorflow machine lacked.
# data/tensorflow/crawl/samples.jsonl was de-duplicated (backup: samples.jsonl.bak-dup).
# Make sure nothing else is crawling with the same tokens. ONE command at a time.
$tf = @('--libs', 'tensorflow', '--cap', '500', '--assign', 'signature', '--search-limit', '5000', '--cache', 'cache_tensorflow')

# 1. Re-read the cached searches and files with the new rules; refills the cells freed by the de-duplication.
#    No search API calls.
& $py -m llm_dep.crawling.run @tf --source github --cached-only --reprocess      # command #3
& $py -m llm_dep.crawling.run @tf --cached-only --reprocess                      # command #2

# 2. New searches: only the new queries are sent, the others are answered from cache_tensorflow.
& $py -m llm_dep.crawling.run @tf --source github --wait-on-block 30 --gh-interval 20   # command #3
& $py -m llm_dep.crawling.run @tf --wait-on-block 60                                     # command #2

# 3. Report
& $py -m llm_dep.crawling.report --export
