$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# Floor of 100 samples per cell (--min-target 100): target = max(largest U / O cell of BEFORE, 100), then --cap.
# Step 1 re-reads the CACHE ONLY (--cached-only --reprocess): no search is sent, files come from the cache.
# Search results are cached per --search-limit on Sourcegraph (2000 = command #1 default, 5000 = command #2),
# so both limits are re-read; GitHub result pages are cached whatever the limit, so #3 uses a large one.
# pytorch has no cache on this machine; seaborn has no cell under 100 that the floor would open.
# Make sure nothing else is crawling with the same tokens. ONE command at a time.
$floor = @('--min-target', '100')                    # the report must use the same floor as the crawl
$m = $floor + @('--cached-only', '--reprocess')
$groups = @(
    @('--libs', 'numpy', 'pandas', 'scikit-learn', 'scipy', '--infer-types'),     # --infer-types only acts on pandas
    @('--libs', 'transformers', '--allow-from-pretrained'),
    @('--libs', 'tensorflow', '--cap', '500', '--cache', 'cache_tensorflow')
)

# 1. Cache only
foreach ($g in $groups) {
    & $py -m llm_dep.crawling.run @g @m                                                             # #1 Sourcegraph, dependency (limit 2000)
    & $py -m llm_dep.crawling.run @g @m --assign signature                                          # #2 on the same searches (limit 2000)
    & $py -m llm_dep.crawling.run @g @m --assign signature --search-limit 5000                      # #2 (limit 5000)
    & $py -m llm_dep.crawling.run @g @m --source github --assign signature --search-limit 40000     # #3
    & $py -m llm_dep.crawling.run @g @m --assign signature --search-limit 5000 --notebooks          # #2 notebooks
    & $py -m llm_dep.crawling.run @g @m --source github --assign signature --search-limit 40000 --notebooks   # #3 notebooks
}

# 2. Report (same floor, otherwise the samples above the old target are trimmed)
& $py -m llm_dep.crawling.report --export @floor
