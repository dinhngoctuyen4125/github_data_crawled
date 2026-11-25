python -m llm_dep.crawling.run --libs scikit-learn --kinds O --source github --assign signature --search-limit 20000 --wait-on-block 30 --gh-interval 20
python -m llm_dep.crawling.run --libs pandas --kinds O --source github --assign signature --search-limit 5000 --infer-types --cached-only --reprocess
python -m llm_dep.crawling.run --libs pandas --kinds O --assign signature --search-limit 5000 --infer-types --cached-only --reprocess
python -m llm_dep.crawling.run --libs seaborn --kinds U --source github --assign signature --search-limit 5000 --wait-on-block 30 --gh-interval 20
python -m llm_dep.crawling.run --libs scipy --source github --assign signature --search-limit 20000 --wait-on-block 30 --gh-interval 20
python -m llm_dep.crawling.report --export
