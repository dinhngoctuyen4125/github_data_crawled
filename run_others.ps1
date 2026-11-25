$py = "C:\Users\tuyen\AppData\Local\Programs\Python\Python311\python.exe"   # Python 3.11: still has lib2to3 (Python 2 files)

# 1. Re-read cached files with the new rules (Python 2 files, relative imports). No GitHub search calls.
& $py -m llm_dep.crawling.run --libs scikit-learn --kinds O --source github --assign signature --search-limit 20000 --cached-only --reprocess
& $py -m llm_dep.crawling.run --libs seaborn --kinds O U --source github --assign signature --search-limit 5000 --cached-only --reprocess
& $py -m llm_dep.crawling.run --libs scipy --kinds O --source github --assign signature --search-limit 20000 --cached-only --reprocess
& $py -m llm_dep.crawling.run --libs pandas --kinds O --source github --assign signature --search-limit 5000 --infer-types --cached-only --reprocess
& $py -m llm_dep.crawling.run --libs transformers --kinds O --source github --assign signature --search-limit 5000 --allow-from-pretrained --cached-only --reprocess
& $py -m llm_dep.crawling.run --libs scikit-learn seaborn scipy --kinds O U --assign signature --search-limit 5000 --cached-only --reprocess
& $py -m llm_dep.crawling.run --libs pandas --kinds O --assign signature --search-limit 5000 --infer-types --cached-only --reprocess

# 2. New GitHub search: GMM beyond the first 20000 hits (long, rate limited).
& $py -m llm_dep.crawling.run --libs scikit-learn --kinds O --source github --assign signature --search-limit 40000 --wait-on-block 30 --gh-interval 20

# 3. Report
& $py -m llm_dep.crawling.report --export
