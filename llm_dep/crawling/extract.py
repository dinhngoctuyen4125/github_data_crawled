"""Extract completion samples (function + prompt + reference + api_call) from a source file."""
import ast
import logging
import threading
import warnings
from typing import Dict, Iterable, List, Optional

# Crawled files often contain invalid escape sequences; ast.parse would warn for each of them.
warnings.filterwarnings("ignore", category=SyntaxWarning)

from llm_dep.data_collection.api_matcher import APIMatcher
from llm_dep.utils.source_utils import extract_first_statement

from .pandas_types import PandasTypes


class CallSiteMatcher(APIMatcher):
    """APIMatcher that keeps the earliest matching call of each function (so the prompt never
    contains the target API), records the exact call source, and also matches indexer access
    such as `df.loc[...]` for APIs in `indexer_apis`. With `from_pretrained`, `Cls.from_pretrained(...)`
    also counts as a use of a class API `Cls` (it builds the object through `cls(**config)`)."""

    def __init__(self, code, apis, indexer_apis=(), maxline=1000, infer_types=False, from_pretrained=False,
                 original=None, package=None):
        super().__init__(code, set(apis) | set(indexer_apis), maxline=maxline)
        self.indexer_apis = set(indexer_apis)
        self.infer_types = infer_types
        self.from_pretrained = from_pretrained
        self.original = original          # lines of the Python 2 source that `code` (its lib2to3 translation) came from
        self.package = package            # dotted package of the file (`package_of`): resolves `from . import x`
        self.tree = None                  # stays None when the code is not valid Python 3
        self.sites: List[dict] = []

    def solve_imports(self):
        """APIMatcher.solve_imports, plus relative imports (`from . import utils`, `from ..utils import despine`)
        resolved against `self.package`; without it they stay unresolved as before."""
        super().solve_imports()
        if not self.package:
            return
        pkg = self.package.split(".")
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.ImportFrom) or not node.level or node.level > len(pkg):
                continue
            base = ".".join(pkg[:len(pkg) - node.level + 1])
            mod = f"{base}.{node.module}" if node.module else base
            for nn in node.names:
                if nn.name == "*":
                    self.import_dict[mod] = mod
                else:
                    self.import_dict[nn.asname or nn.name] = f"{mod}.{nn.name}"

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
            api, reason, form = self._resolve(name, ref_dict), None, "call"
            if (api not in wanted and self.from_pretrained and isinstance(node, ast.Call)
                    and isinstance(callee, ast.Attribute) and callee.attr == "from_pretrained"):
                cls_name = self.get_source_by_node(callee.value)
                cls_api = self._resolve(cls_name, ref_dict) if cls_name else None
                if cls_api in wanted and cls_api.split(".")[-1][:1].isupper():
                    api, name, form = cls_api, cls_name, "from_pretrained"
            if api not in wanted and types is not None and isinstance(callee, ast.Attribute):
                t = types.infer(callee.value, node.lineno)      # e.g. df <- pd.read_csv(...)
                if t:
                    api, reason = f"{t[0]}.{callee.attr}", t[1]
            if api not in wanted:
                continue
            key = (node.lineno, node.col_offset)
            if best is None or key < best[0]:
                best = (key, node, name, api, reason, form)
        return best

    def match_one_func(self, func, ref_dict):
        if func.end_lineno - func.lineno > self.maxline:
            return
        ref_dict = dict(ref_dict or {})
        ref_dict.update(self.extract_local_ref_dict(func))
        best = self._best(func, ref_dict, func.lineno, func.end_lineno, scope=func)
        if best is None:
            return
        _, node, name, api, reason, form = best
        self._record(" " * func.col_offset + self.get_source_by_node(func), func.lineno, node, name, api, ref_dict,
                     reason, form)

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
            _, node, name, api, reason, form = best
            first, last = block[0], block[-1]
            src = self.get_source_by_position(first.lineno - 1, first.col_offset, last.end_lineno - 1, last.end_col_offset)
            self._record(" " * first.col_offset + src, first.lineno, node, name, api, self.global_ref_dict,
                         reason, form)
            return

    def _original_lines(self, lines: List[str], first_lineno: int, node):
        """`lines` of a site found in the lib2to3 translation, rebuilt from the original Python 2 source
        (`extract_sites` only translates files whose line count lib2to3 keeps, so line i maps to line i).
        The call's own lines must be unchanged (so `api_call` is original text); otherwise None. Unchanged lines
        keep the matcher's cut (indent of the first line, end of the last statement); lines changed by lib2to3
        are taken whole."""
        c0 = first_lineno - 1
        orig = self.original[c0:c0 + len(lines)]
        same = [c.rstrip("\r\n") == o for c, o in zip(self.lines[c0:c0 + len(lines)], orig)]
        if not all(same[node.lineno - first_lineno:node.end_lineno - first_lineno + 1]):
            return None
        return [l if s else o.rstrip() for l, s, o in zip(lines, same, orig)]

    def _record(self, function: str, first_lineno: int, node, call_name: str, api: str, ref_dict: dict,
                reason=None, form="call"):
        rel = node.lineno - first_lineno
        lines = function.split("\n")
        if self.original is not None:
            lines = self._original_lines(lines, first_lineno, node)
            if lines is None:
                return
            function = "\n".join(lines)
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
            "call form": form,
        })


# lib2to3 (deprecated since 3.11, removed in 3.13) is only used to locate call sites in Python 2 files.
# Only the fixers for Python 2 *syntax* are applied: every other fixer (e.g. fix_unicode: u"a" -> "a") rewrites
# valid code, and a rewritten call line can no longer be mapped back to the original text.
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from lib2to3.refactor import RefactoringTool
except ImportError:
    RefactoringTool = None
    logging.warning("lib2to3 is not available (Python >= 3.13): Python 2 files will yield no samples")
PY2_SYNTAX_FIXERS = [f"lib2to3.fixes.fix_{n}" for n in (
    "print", "except", "exec", "raise", "repr", "ne", "numliterals", "tuple_params", "paren")]
_py2 = threading.local()                    # RefactoringTool is not thread-safe; run.py extracts in a pool


def _py2to3(code: str) -> Optional[str]:
    """lib2to3 translation of Python 2 source (None if it fails or lib2to3 is unavailable)."""
    if RefactoringTool is None:
        return None
    if not hasattr(_py2, "tool"):
        _py2.tool = RefactoringTool(PY2_SYNTAX_FIXERS)
    try:
        return str(_py2.tool.refactor_string(code, "<crawled>"))      # code ends with "\n" (extract_sites)
    except Exception:
        return None


def package_of(path: Optional[str], tops: Iterable[str]) -> Optional[str]:
    """Dotted package of the file at repository `path`, from the last directory named like one of the libraries
    `tops` (`src/seaborn/tests/test_utils.py` -> `seaborn.tests`); None if no such directory, i.e. the file is not a
    copy of the library's own source, so its relative imports refer to some other package."""
    if not path:
        return None
    dirs = path.replace("\\", "/").split("/")[:-1]
    for i in range(len(dirs) - 1, -1, -1):
        if dirs[i] in tops:
            rest = dirs[i:]
            return ".".join(rest) if all(d.isidentifier() for d in rest) else None
    return None


def _match(code: str, apis, indexer_apis, infer_types, from_pretrained, original=None,
           package=None) -> Optional[CallSiteMatcher]:
    m = CallSiteMatcher(code, apis, indexer_apis, infer_types=infer_types, from_pretrained=from_pretrained,
                        original=original, package=package)
    try:
        return m.match()
    except (RecursionError, IndexError, ValueError):
        return None


def extract_sites(code: str, apis: Iterable[str], indexer_apis: Iterable[str] = (),
                  infer_types: bool = False, from_pretrained: bool = False, path: Optional[str] = None) -> List[Dict]:
    """Call sites of `apis` in `code`. A file that is not valid Python 3 (Python 2) is translated with lib2to3
    to find the sites; their text is then taken from the original lines (`CallSiteMatcher._original_lines`).
    `path` (repository path of the file) lets relative imports inside a copy of the library resolve (`package_of`)."""
    apis, indexer_apis = set(apis), set(indexer_apis)
    package = package_of(path, {a.split(".", 1)[0] for a in apis | indexer_apis})
    m = _match(code, apis, indexer_apis, infer_types, from_pretrained, package=package)
    if m is None:
        return []
    if m.tree is not None:
        return m.sites
    names = {a.rsplit(".", 1)[-1] for a in apis | indexer_apis} | ({"from_pretrained"} if from_pretrained else set())
    if not any(n in code for n in names):   # cannot contain a site: skip the (slow) translation
        return []
    text = code.replace("\r\n", "\n").replace("\r", "\n")
    text += "" if text.endswith("\n") else "\n"
    new = _py2to3(text)
    if new is None or new.count("\n") != text.count("\n"):    # line count changed (fix_tuple_params): no 1:1 map
        return []
    m = _match(new, apis, indexer_apis, infer_types, from_pretrained, original=text.split("\n"), package=package)
    return [] if m is None or m.tree is None else m.sites
