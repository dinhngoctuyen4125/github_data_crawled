$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# Signature fix: an unbound call `pd.DataFrame.pad(x)` passes `self` (x) explicitly.
# Re-read cached pandas O files with the new rule (no search API calls). The 7 `pd.DataFrame.pad(...)` samples
# were removed from data/pandas/crawl/samples.jsonl (backup: samples.jsonl.bak-unbound-self) so that they are
# accepted again with their 2.x milestones. Run one command at a time.
& $py -m llm_dep.crawling.run --libs pandas --kinds O --assign signature --search-limit 2000 --infer-types --cached-only --reprocess   # Sourcegraph searches were cached with the default limit 2000
& $py -m llm_dep.crawling.run --libs pandas --kinds O --source github --assign signature --search-limit 5000 --infer-types --cached-only --reprocess

# Report
& $py -m llm_dep.crawling.report --export
