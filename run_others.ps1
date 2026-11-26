$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# Floor of 100 samples per cell (--min-target 100): target = max(largest U / O cell of BEFORE, 100), then --cap.
# Make sure nothing else is crawling with the same tokens. ONE command at a time.
# Re-running resumes, except the --reprocess commands of step 1, which start their command over (no duplicates).
$floor = @('--min-target', '100')                    # the report must use the same floor as the crawl
$g4 = @('--libs', 'pandas', 'scipy', 'scikit-learn', 'numpy', '--infer-types')   # --infer-types only acts on pandas
$tr = @('--libs', 'transformers', '--allow-from-pretrained')
$tf = @('--libs', 'tensorflow', '--cap', '500', '--cache', 'cache_tensorflow')

# 1. Cache only (--cached-only --reprocess): no search is sent, files come from the cache.
#    Sourcegraph results are cached per --search-limit (2000 = command #1 default, 5000 = command #2), so both are
#    re-read; GitHub result pages are cached whatever the limit, so #3 uses a large one.
#    pytorch has no cache on this machine; seaborn has no cell under 100 that the floor would open.
$c = $floor + @('--cached-only', '--reprocess')
foreach ($g in @($g4, $tr, $tf)) {
    & $py -m llm_dep.crawling.run @g @c                                                             # #1 Sourcegraph, dependency (limit 2000)
    & $py -m llm_dep.crawling.run @g @c --assign signature                                          # #2 on the same searches (limit 2000)
    & $py -m llm_dep.crawling.run @g @c --assign signature --search-limit 5000                      # #2 (limit 5000)
    & $py -m llm_dep.crawling.run @g @c --source github --assign signature --search-limit 40000     # #3
    & $py -m llm_dep.crawling.run @g @c --assign signature --search-limit 5000 --notebooks          # #2 notebooks
    & $py -m llm_dep.crawling.run @g @c --source github --assign signature --search-limit 40000 --notebooks   # #3 notebooks
}
& $py -m llm_dep.crawling.report --export @floor

# 2. Batch A, new Sourcegraph searches (a few hours): only queries not in the cache are sent.
foreach ($g in @($g4, $tr)) {
    & $py -m llm_dep.crawling.run @g @floor --wait-on-block 60                                      # #1 dependency
    & $py -m llm_dep.crawling.run @g @floor --assign signature --search-limit 5000 --wait-on-block 60   # #2 signature
}
& $py -m llm_dep.crawling.report --export @floor

# 3. Batch B, new GitHub searches (~137 queries, 5-25 min each: 11-57 h; stop / resume at any time).
#    pandas and scipy first. No transformers / tensorflow: rare APIs, sources nearly exhausted.
& $py -m llm_dep.crawling.run @g4 @floor --source github --assign signature --search-limit 5000 --wait-on-block 30 --gh-interval 20   # #3
& $py -m llm_dep.crawling.report --export @floor
