"""Check whether a concrete call (`api_call`) can bind to an API signature at a milestone.

Signatures come from migration_evolution.json and may use Python syntax
(`numpy.all(a, axis=None, *, keepdims=<no value>)`) or ATen schema syntax
(`torch.linalg.norm(self: Tensor, ord: Scalar?=None, dim: int[1]?=None)`), so they are parsed
with a tolerant splitter instead of `ast`.
"""
import ast
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import List, Optional, Tuple

from .evolution import USABLE, ApiState


@dataclass
class Params:
    positional: List[Tuple[str, bool]] = field(default_factory=list)   # (name, has_default), incl. pos-only
    n_posonly: int = 0
    kwonly: List[Tuple[str, bool]] = field(default_factory=list)
    varargs: bool = False
    varkw: bool = False
    bare_self: bool = False   # first parameter is an unannotated `self`/`cls` (Python method)


def _split_top(s: str) -> List[str]:
    parts, depth, cur, quote = [], 0, [], None
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur)); cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


@lru_cache(maxsize=None)
def parse_signature(sig: str) -> Optional[Params]:
    i, j = sig.find("("), sig.rfind(")")
    if i < 0 or j < i:
        return None
    p = Params()
    kw_only = False
    for raw in _split_top(sig[i + 1:j]):
        if raw == "/":
            p.n_posonly = len(p.positional)
            continue
        if raw == "*":
            kw_only = True
            continue
        if raw.startswith("**"):
            p.varkw = True
            continue
        if raw.startswith("*"):
            p.varargs = True
            kw_only = True
            continue
        m = re.match(r"([A-Za-z_]\w*)", raw)
        if not m:
            return None
        name = m.group(1)
        if not p.positional and not p.kwonly and name in ("self", "cls") and ":" not in raw:
            p.bare_self = True
        has_default = bool(re.search(r"(?<![=!<>])=(?!=)", raw))
        (p.kwonly if kw_only else p.positional).append((name, has_default))
    return p


@dataclass
class Call:
    n_pos: int                   # explicit positional arguments (starred ones excluded)
    keywords: List[str]          # explicit keyword names (`**kw` excluded)
    subscript: bool = False      # obj.loc[...] (indexer access, no call)
    star: bool = False           # has `*args`
    dstar: bool = False          # has `**kwargs`
    n_pos_fixed: int = 0         # explicit positionals before the first `*args` (their slots are known)
    receiver: Optional[str] = None   # dotted name before `.method` (`pd.DataFrame` in `pd.DataFrame.pad(x)`)

    @property
    def starred(self) -> bool:
        return self.star or self.dstar


def parse_call(src: str, allow_starred: bool = False) -> Optional[Call]:
    """Parse an `api_call` string. None when unparsable, or when it has `*args` / `**kwargs`
    and allow_starred is False (the binding is then undecidable)."""
    try:
        node = ast.parse(src.strip(), mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Subscript):
        inner = node.value
        if isinstance(inner, ast.Call):          # obj.loc(axis=0)[key]
            node = inner
        else:
            return Call(0, [], subscript=True)
    if not isinstance(node, ast.Call):
        return None
    star = any(isinstance(a, ast.Starred) for a in node.args)
    dstar = any(k.arg is None for k in node.keywords)
    if (star or dstar) and not allow_starred:
        return None
    first_star = next((i for i, a in enumerate(node.args) if isinstance(a, ast.Starred)), len(node.args))
    return Call(sum(not isinstance(a, ast.Starred) for a in node.args),
                [k.arg for k in node.keywords if k.arg is not None],
                star=star, dstar=dstar, n_pos_fixed=first_star,
                receiver=_dotted(node.func.value) if isinstance(node.func, ast.Attribute) else None)


def _dotted(node) -> Optional[str]:
    """`a.b.c` for a plain Name/Attribute chain, None otherwise (e.g. `f(x).g`)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _unbound_as_bound(call: Call, api: str) -> Optional[Call]:
    """`pkg.Class.method(x, ...)` passes `self` explicitly (x): the same call as `x.method(...)`, so it is checked
    with its first positional removed. Calls on an instance (`df.pad()`, `f(x).pad()`) are returned unchanged;
    None for an unbound call without any positional (no `self`)."""
    if not is_method(api) or not call.receiver or call.receiver.split(".")[-1] != api.split(".")[-2]:
        return call
    if call.n_pos_fixed >= 1:
        return replace(call,n_pos=call.n_pos - 1, n_pos_fixed=call.n_pos_fixed - 1)
    return call if call.star else None          # `*args` may supply `self`


def is_method(api: str) -> bool:
    """`pkg.Class.method` -> bound call, the leading `self` is supplied by the receiver."""
    parts = api.split(".")
    return len(parts) >= 3 and parts[-2][:1].isupper()


def _drop_self(params: Params, drop_self: bool):
    pos = list(params.positional)
    nposonly = params.n_posonly
    if (drop_self or params.bare_self) and pos and pos[0][0] in ("self", "cls"):
        pos = pos[1:]
        nposonly = max(0, nposonly - 1)
    return pos, nposonly


def binds_starred(call: Call, params: Params, drop_self: bool) -> bool:
    """Lenient binding for calls with `*args` / `**kwargs` (as in the original O/U data): the
    starred parts may be empty or fill any missing parameter, so the call binds unless its
    explicit part already fails (too many positionals, unknown / duplicated / positional-only keyword)."""
    pos, nposonly = _drop_self(params, drop_self)
    names = [n for n, _ in pos]
    if call.n_pos > len(pos) and not params.varargs:
        return False
    filled = set(names[: call.n_pos_fixed])
    kw_names = {n for n, _ in params.kwonly}
    for k in call.keywords:
        if k in names[:nposonly] and not params.varkw:
            return False
        if k in filled:
            return False
        if not (k in names[nposonly:] or k in kw_names or params.varkw):
            return False
        filled.add(k)
    return True


def binds(call: Call, params: Params, drop_self: bool) -> bool:
    if call.starred:
        return binds_starred(call, params, drop_self)
    pos, nposonly = _drop_self(params, drop_self)
    names = [n for n, _ in pos]
    if call.n_pos > len(pos) and not params.varargs:
        return False
    filled = set(names[: call.n_pos])
    kw_names = {n for n, _ in params.kwonly}
    for k in call.keywords:
        if k in names[:nposonly] and not params.varkw:
            return False
        if k in filled:
            return False
        if k in names[nposonly:] or k in kw_names:
            filled.add(k)
        elif not params.varkw:
            return False
    if any(not d and n not in filled for n, d in pos):
        return False
    if any(not d and n not in filled for n, d in params.kwonly):
        return False
    return True


def compatible(api_call: str, api: str, state: Optional[ApiState], lenient_starred: bool = False) -> Optional[bool]:
    """True/False when decidable, None when the call cannot be checked (starred args...).
    lenient_starred: calls with `*args` / `**kwargs` bind unless their explicit part fails."""
    if state is None or state.status not in USABLE:
        return False
    call = parse_call(api_call, allow_starred=lenient_starred)
    if call is None:
        return None
    cs = state.call_syntax
    if cs and cs.get("kind") == "indexer":
        forms = cs.get("forms", [])
        if call.subscript:
            return any(f.endswith("[key]") and "(" not in f for f in forms)
        allowed = set()
        for f in forms:
            m = re.search(r"\((.*)\)", f)
            if m:
                allowed |= {a.split("=")[0].strip() for a in m.group(1).split(",") if a.strip()}
        return call.n_pos == 0 and bool(allowed) and set(call.keywords) <= allowed
    if cs and cs.get("kind") == "ufunc":
        n_in = cs.get("required_inputs", 0)
        kws_ok = all(k in ("out", "where", "casting", "order", "dtype", "subok", "signature") for k in call.keywords)
        n_max = n_in + cs.get("outputs", 1)
        if call.star:                              # `*args` may supply the missing inputs
            return call.n_pos <= n_max and kws_ok
        return call.n_pos in (n_in, n_max) and kws_ok
    if call.subscript:
        return False
    call = _unbound_as_bound(call, api)
    if call is None:
        return False
    drop_self = is_method(api) or api.split(".")[-1][:1].isupper()   # bound method or class constructor
    for sig in state.signatures:
        params = parse_signature(sig)
        if params is not None and binds(call, params, drop_self):
            return True
    return False
