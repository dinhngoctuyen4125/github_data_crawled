"""Extract completion samples (function + prompt + reference + api_call) from a source file."""
import ast
import warnings
from typing import Dict, Iterable, List

# Crawled files often contain invalid escape sequences; ast.parse would warn for each of them.
warnings.filterwarnings("ignore", category=SyntaxWarning)

from llm_dep.data_collection.api_matcher import APIMatcher
from llm_dep.utils.source_utils import extract_first_statement

from .pandas_types import PandasTypes


class CallSiteMatcher(APIMatcher):
    """APIMatcher that keeps the earliest matching call of each function (so the prompt never
    contains the target API), records the exact call source, and also matches indexer access
    such as `df.loc[...]` for APIs in `indexer_apis`."""

    def __init__(self, code, apis, indexer_apis=(), maxline=1000, infer_types=False):
        super().__init__(code, set(apis) | set(indexer_apis), maxline=maxline)
        self.indexer_apis = set(indexer_apis)
        self.infer_types = infer_types
        self.sites: List[dict] = []

    def _resolve(self, name: str, ref_dict: dict) -> str:
        parts = name.split(".")
        if len(parts) >= 2:
            q = ".".join(parts[:-1])
            if q in ref_dict:
                name = f"{ref_dict[q]}.{parts[-1]}"
        return self.alias_dict.get(name, name)

    def _candidates(self, root):
        for node in ast.walk(root):
            if isinstance(node, ast.Call):
                yield node, node.func
            elif isinstance(node, ast.Subscript) and self.indexer_apis and isinstance(node.value, ast.Attribute):
                yield node, node.value

    def _best(self, root, ref_dict, first_line, last_line, scope=None):
        best = None
        types = None
        if self.infer_types:
            scope = scope if scope is not None else root
            cache = self.__dict__.setdefault("_types", {})
            types = cache.get(id(scope)) or cache.setdefault(id(scope), PandasTypes(self, scope))
        for node, callee in self._candidates(root):
            if not (first_line <= node.lineno <= last_line):
                continue
            name = self.get_source_by_node(callee)
            if not name:
                continue
            wanted = self.indexer_apis if isinstance(node, ast.Subscript) else self.apis
            api, reason = self._resolve(name, ref_dict), None
            if api not in wanted and types is not None and isinstance(callee, ast.Attribute):
                t = types.infer(callee.value, node.lineno)      # e.g. df <- pd.read_csv(...)
                if t:
                    api, reason = f"{t[0]}.{callee.attr}", t[1]
            if api not in wanted:
                continue
            key = (node.lineno, node.col_offset)
            if best is None or key < best[0]:
                best = (key, node, name, api, reason)
        return best

    def match_one_func(self, func, ref_dict):
        if func.end_lineno - func.lineno > self.maxline:
            return
        ref_dict = dict(ref_dict or {})
        ref_dict.update(self.extract_local_ref_dict(func))
        best = self._best(func, ref_dict, func.lineno, func.end_lineno, scope=func)
        if best is None:
            return
        _, node, name, api, reason = best
        self._record(" " * func.col_offset + self.get_source_by_node(func), func.lineno, node, name, api, ref_dict, reason)

    def match_script_stmts(self, max_stmts=5):
        block = []
        for stmt in self.tree.body:
            if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Import, ast.ImportFrom)):
                block = []
                continue
            block.append(stmt)
            block = block[-max_stmts:]
            if len(block) == 1:
                continue
            best = self._best(stmt, self.global_ref_dict, stmt.lineno, stmt.end_lineno, scope=self.tree)
            if best is None:
                continue
            _, node, name, api, reason = best
            first, last = block[0], block[-1]
            src = self.get_source_by_position(first.lineno - 1, first.col_offset, last.end_lineno - 1, last.end_col_offset)
            self._record(" " * first.col_offset + src, first.lineno, node, name, api, self.global_ref_dict, reason)
            return

    def _record(self, function: str, first_lineno: int, node, call_name: str, api: str, ref_dict: dict,
                reason=None):
        rel = node.lineno - first_lineno
        lines = function.split("\n")
        if rel <= 0 or rel >= len(lines):
            return                       # call on the def line: no prompt to complete from
        self.sites.append({
            "function": function,
            "probing input": "\n".join(lines[:rel]) + "\n",
            "reference": extract_first_statement("\n".join(lines[rel:])),
            "api_call": self.get_source_by_node(node),
            "call name": call_name,
            "matched api": api,
            "alias dict": self.alias_dict,
            "reference dict": ref_dict,
            "type inference": reason,
        })


def extract_sites(code: str, apis: Iterable[str], indexer_apis: Iterable[str] = (),
                  infer_types: bool = False) -> List[Dict]:
    m = CallSiteMatcher(code, apis, indexer_apis, infer_types=infer_types)
    try:
        m.match()
    except (RecursionError, IndexError, ValueError):
        return []
    return m.sites
