"""Version-aware crawling of API usages.

Pipeline: search code (Sourcegraph) -> download file at commit -> extract functions calling a
target API -> resolve the library version from the repo's dependency files -> place the call at
milestone v1 of the evolution path when the version lies in [v1, v2) and the call matches the
API signature at v1 -> keep it only if that (mapping, U/O, milestone) cell still needs samples.
"""
