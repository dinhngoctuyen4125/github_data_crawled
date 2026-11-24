"""Conservative type inference for pandas receivers (opt-in with --infer-types).

APIMatcher only knows a variable's type when it is assigned from a capitalised call such as
`df = pd.DataFrame(...)`. This module also recognises expressions whose type is certain:

1. pandas readers / constructors that always return a DataFrame (`pd.read_csv`, `pd.merge`...),
   except when they return iterators or dicts (`chunksize=`, `iterator=True`,
   `read_excel(sheet_name=None | [...])`);
2. DataFrame / Series methods that return the same type (`df.copy()`, `df.dropna()`...),
   except with `inplace=True` (returns None);
3. `df["col"]` with a constant string key -> Series;
4. `df.style` and Styler methods that return a Styler -> Styler;
5. parameters annotated `pd.DataFrame` / `pd.Series`, and `df.T`.

Deliberately excluded (may return another type): pd.concat, read_json, read_hdf, read_pickle,
read_html, df.apply, df.col attribute access, groupby(...).agg(...).
A variable takes the type of its latest assignment before the call line in the same scope.
"""
import ast
from typing import Dict, List, Optional, Tuple

DF, SERIES, STYLER = "pandas.DataFrame", "pandas.Series", "pandas.io.formats.style.Styler"

DF_FACTORIES = {f"pandas.{n}" for n in (
    "read_csv", "read_table", "read_excel", "read_parquet", "read_feather", "read_sql", "read_sql_query",
    "read_sql_table", "read_fwf", "read_stata", "read_orc", "read_xml", "read_clipboard", "read_spss",
    "read_sas", "merge", "pivot_table", "crosstab", "get_dummies", "melt", "json_normalize",
    "DataFrame", "DataFrame.from_dict", "DataFrame.from_records",
)} | {"pandas.io.json.json_normalize"}
SERIES_FACTORIES = {"pandas.Series"}
ITERATOR_KWARGS = {"chunksize", "iterator"}

DF_SAME = {"copy", "dropna", "fillna", "reset_index", "sort_values", "sort_index", "drop", "drop_duplicates",
           "rename", "astype", "set_index", "query", "assign", "head", "tail", "merge", "join", "round",
           "replace", "sample", "transpose", "ffill", "bfill", "abs", "clip", "where", "mask", "reindex",
           "rename_axis", "applymap", "map"}
SERIES_SAME = {"copy", "dropna", "fillna", "sort_values", "sort_index", "astype", "head", "tail", "round",
               "replace", "sample", "ffill", "bfill", "abs", "clip", "where", "mask", "rename", "map"}
STYLER_SAME = {"apply", "applymap", "map", "format", "format_index", "highlight_max", "highlight_min",
               "highlight_null", "highlight_between", "highlight_quantile", "background_gradient",
               "text_gradient", "bar", "set_properties", "set_table_styles", "set_table_attributes",
               "set_caption", "set_precision", "set_na_rep", "set_td_classes", "set_tooltips", "set_uuid",
               "hide", "hide_index", "hide_columns", "relabel_index", "set_sticky", "use", "pipe"}
ANNOTATIONS = {"pandas.DataFrame": DF, "pandas.core.frame.DataFrame": DF,
               "pandas.Series": SERIES, "pandas.core.series.Series": SERIES}

Typed = Optional[Tuple[str, str]]      # (type, reason)


def _kw(call: ast.Call, name: str):
    return next((k.value for k in call.keywords if k.arg == name), None)


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


class PandasTypes:
    def __init__(self, matcher, scope: ast.AST):
        self.m = matcher
        self.assigns: Dict[str, List[Tuple[int, ast.AST]]] = {}
        self.params: Dict[str, str] = {}
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = scope.args
            for a in args.posonlyargs + args.args + args.kwonlyargs:
                t = self._annotation(a.annotation)
                if t:
                    self.params[a.arg] = t
        for node in ast.walk(scope):
            target, value = None, None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                target, value = node.target.id, node.value
            if target:
                self.assigns.setdefault(target, []).append((node.lineno, value))
        for v in self.assigns.values():
            v.sort(key=lambda x: x[0])

    # ------------------------------------------------------------------ helpers
    def _fq(self, node) -> Optional[str]:
        """Fully qualified dotted name of a Name/Attribute chain, through the file's imports."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.insert(0, node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        head = self.m.import_dict.get(node.id)
        if head is None:
            return None
        return ".".join([head] + parts)

    def _annotation(self, ann) -> Optional[str]:
        if ann is None:
            return None
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            try:
                ann = ast.parse(ann.value, mode="eval").body
            except SyntaxError:
                return None
        return ANNOTATIONS.get(self._fq(ann) or "")

    def _src(self, node, limit=60) -> str:
        s = " ".join(self.m.get_source_by_node(node).split())
        return s if len(s) <= limit else s[:limit] + "..."

    # ------------------------------------------------------------------ inference
    def infer(self, node, line: int, depth: int = 0) -> Typed:
        if depth > 8:
            return None
        if isinstance(node, ast.Name):
            return self._var(node.id, line, depth)
        if isinstance(node, ast.Call):
            return self._call(node, line, depth)
        if isinstance(node, ast.Attribute):
            base = self.infer(node.value, line, depth + 1)
            if base and base[0] == DF and node.attr == "T":
                return DF, base[1]
            if base and base[0] == DF and node.attr == "style":
                return STYLER, base[1]
            return None
        if isinstance(node, ast.Subscript):
            base = self.infer(node.value, line, depth + 1)
            key = node.slice
            if base and base[0] == DF and isinstance(key, ast.Constant) and isinstance(key.value, str):
                return SERIES, base[1]
        return None

    def _var(self, name: str, line: int, depth: int) -> Typed:
        before = [(ln, v) for ln, v in self.assigns.get(name, []) if ln < line]
        if before:
            ln, value = before[-1]                      # latest assignment before the use
            t = self.infer(value, ln, depth + 1)
            return (t[0], f"{name} <- {t[1]}") if t else None
        if name in self.params:
            return self.params[name], f"{name}: {self.params[name].split('.')[-1]} (annotation)"
        return None

    def _call(self, call: ast.Call, line: int, depth: int) -> Typed:
        fq = self._fq(call.func)
        if fq in DF_FACTORIES:
            if any(k.arg in ITERATOR_KWARGS for k in call.keywords):
                return None
            if fq == "pandas.read_excel":
                sheet = _kw(call, "sheet_name")
                if sheet is not None and (isinstance(sheet, (ast.List, ast.Tuple))
                                          or (isinstance(sheet, ast.Constant) and sheet.value is None)):
                    return None
            return DF, self._src(call)
        if fq in SERIES_FACTORIES:
            return SERIES, self._src(call)
        if isinstance(call.func, ast.Attribute):
            if _is_true(_kw(call, "inplace")):
                return None
            base = self.infer(call.func.value, line, depth + 1)
            method = call.func.attr
            if base:
                if base[0] == DF and method in DF_SAME:
                    return DF, base[1]
                if base[0] == SERIES and method in SERIES_SAME:
                    return SERIES, base[1]
                if base[0] == STYLER and method in STYLER_SAME:
                    return STYLER, base[1]
        return None
