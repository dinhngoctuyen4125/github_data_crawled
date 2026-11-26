"""Find and parse a repository's dependency declarations (requirements, pyproject, setup.py/cfg, Pipfile, lock files, environment.yml)."""
import ast
import configparser
import json
import posixpath
import re
import tomllib
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from .evolution import parse_version

LOCK_FILES = {"poetry.lock", "pipfile.lock", "uv.lock"}
# Probed when the repository tree cannot be listed.
PROBE_NAMES = ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock",
               "poetry.lock", "environment.yml", "environment.yaml", "requirements-dev.txt", "uv.lock"]


def file_kind(path: str) -> Optional[str]:
    base = posixpath.basename(path).lower()
    parent = posixpath.basename(posixpath.dirname(path)).lower()
    if base in LOCK_FILES:
        return base
    if base in ("pyproject.toml", "setup.py", "setup.cfg", "pipfile"):
        return base
    if re.fullmatch(r"(environment|conda|env)[\w\-.]*\.ya?ml", base):
        return "conda"
    if base.endswith(".txt") and ("requirements" in base or parent in ("requirements", "requirement", "reqs")):
        return "requirements"
    return None


def dep_dir(path: str) -> str:
    """Directory a dependency file applies to (requirements/x.txt applies to its parent)."""
    d = posixpath.dirname(path)
    if posixpath.basename(d).lower() in ("requirements", "requirement", "reqs") and file_kind(path) == "requirements":
        d = posixpath.dirname(d)
    return d


@dataclass
class Spec:
    file: str
    package: str
    raw: str
    alternatives: List[SpecifierSet] = field(default_factory=list)   # OR of specifier sets
    exact: Optional[str] = None                                       # exact pin / locked version

    def bounds(self):
        """(has_lower, has_upper): whether the declaration bounds the version from below / above.
        With OR alternatives (Poetry `||`) every alternative must be bounded."""
        if self.exact:
            return True, True
        lows, ups = [], []
        for spec in self.alternatives or [SpecifierSet("")]:
            ops = {sp.operator for sp in spec}
            lows.append(bool(ops & {">=", ">", "==", "~=", "==="}))
            ups.append(bool(ops & {"<", "<=", "==", "~=", "==="}))
        return all(lows), all(ups)

    def candidates(self, releases: Iterable[Version]) -> Set[Version]:
        if self.exact:
            v = parse_version(self.exact)
            return {Version(v.public)} if v else set()
        out = set()
        for spec in self.alternatives or [SpecifierSet("")]:
            out |= {v for v in releases if spec.contains(v, prereleases=False)}
            pin = _single_pin(spec)
            if pin is not None:          # ==X that is not on PyPI (old torch builds, local wheels)
                out.add(pin)
        return out


def _single_pin(spec: SpecifierSet) -> Optional[Version]:
    items = list(spec)
    if len(items) == 1 and items[0].operator in ("==", "===") and "*" not in items[0].version:
        v = parse_version(items[0].version)
        return Version(v.public) if v else None
    return None


def _specset(s: str) -> Optional[SpecifierSet]:
    s = s.strip().replace(" ", "")
    try:
        return SpecifierSet(s)
    except InvalidSpecifier:
        return None


def _poetry_constraint(c: str) -> Optional[List[SpecifierSet]]:
    alts = []
    for part in c.split("||"):
        part = part.strip()
        if part in ("", "*"):
            alts.append(SpecifierSet(""))
            continue
        clauses = []
        for tok in re.split(r"\s*,\s*|\s+(?=[<>=!~^])", part):
            tok = tok.strip()
            if not tok:
                continue
            if tok.startswith("^"):
                nums = [int(x) for x in re.findall(r"\d+", tok)]
                if not nums:
                    return None
                i = next((k for k, n in enumerate(nums) if n != 0), len(nums) - 1)
                upper = nums[:i] + [nums[i] + 1]
                clauses += [f">={tok[1:]}", "<" + ".".join(map(str, upper))]
            elif tok.startswith("~") and not tok.startswith("~="):
                nums = [int(x) for x in re.findall(r"\d+", tok)]
                if not nums:
                    return None
                upper = [nums[0] + 1] if len(nums) == 1 else [nums[0], nums[1] + 1]
                clauses += [f">={tok[1:]}", "<" + ".".join(map(str, upper))]
            elif re.fullmatch(r"\d[\w.*]*", tok):
                clauses.append(f"=={tok}")
            else:
                clauses.append(tok)
        ss = _specset(",".join(clauses))
        if ss is None:
            return None
        alts.append(ss)
    return alts


def _from_requirement_string(line: str, file: str, packages: Set[str]) -> Optional[Spec]:
    line = line.strip()
    if not line:
        return None
    try:
        req = Requirement(line)
        name, spec = req.name, req.specifier
    except InvalidRequirement:
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9_.\-]*)\s*(?:\[[^\]]*\])?\s*([^;#]*)", line)
        if not m:
            return None
        name = m.group(1)
        spec = _specset(m.group(2))
        if spec is None:
            return None
    if canonicalize_name(name) not in packages:
        return None
    return Spec(file, canonicalize_name(name), line, [spec])


def parse_requirements(text: str, file: str, packages: Set[str]) -> List[Spec]:
    out = []
    text = re.sub(r"\\\r?\n", " ", text)
    for line in text.splitlines():
        line = re.split(r"\s#", line)[0].strip()
        if not line or line.startswith(("#", "-")) or "://" in line or line.startswith("git+"):
            continue
        s = _from_requirement_string(line, file, packages)
        if s:
            out.append(s)
    return out


def parse_conda(text: str, file: str, packages: Set[str]) -> List[Spec]:
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*-\s*([^#]+)", line)
        if not m:
            continue
        item = m.group(1).strip().strip("'\"")
        if item.endswith(":"):
            continue                                    # "- pip:" header
        item = item.split("::")[-1]
        cm = re.match(r"([A-Za-z0-9][A-Za-z0-9_.\-]*)\s*(.*)$", item)
        if not cm or canonicalize_name(cm.group(1)) not in packages:
            continue
        name, rest = canonicalize_name(cm.group(1)), cm.group(2).strip()
        if re.match(r"[<>!~]|==", rest) or not rest:
            spec = _specset(rest.split("=")[0] if rest.startswith("=") and not rest.startswith("==") else rest)
            if spec is None:
                continue
            out.append(Spec(file, name, item, [spec]))
            continue
        # conda match spec: "=1.19" / "=1.19.2=build" / "1.19.*" / "1.19.2"
        ver = rest.lstrip("=").split("=")[0].strip()
        if not ver:
            continue
        nparts = len(ver.rstrip(".*").split("."))
        if rest.startswith("=") and not rest.startswith("==") and nparts < 3 and "*" not in ver:
            ver = ver + ".*"                             # "=1.19" means 1.19.*
        spec = _specset(f"=={ver}")
        if spec is not None:
            out.append(Spec(file, name, item, [spec]))
    return out


def _poetry_table(table: dict, file: str, packages: Set[str]) -> List[Spec]:
    out = []
    for name, val in (table or {}).items():
        if canonicalize_name(name) not in packages:
            continue
        vals = val if isinstance(val, list) else [val]
        alts = []
        for v in vals:
            c = v if isinstance(v, str) else (v.get("version") if isinstance(v, dict) else None)
            if c is None:
                alts.append(SpecifierSet(""))
                continue
            conv = _poetry_constraint(c)
            if conv is None:
                alts = None
                break
            alts += conv
        if alts is not None:
            out.append(Spec(file, canonicalize_name(name), f"{name} = {val!r}", alts))
    return out


def parse_pyproject(text: str, file: str, packages: Set[str]) -> List[Spec]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    strings = list(data.get("project", {}).get("dependencies", []) or [])
    for lst in (data.get("project", {}).get("optional-dependencies", {}) or {}).values():
        strings += lst
    for lst in (data.get("dependency-groups", {}) or {}).values():
        strings += [x for x in lst if isinstance(x, str)]
    out = [s for x in strings if isinstance(x, str) and (s := _from_requirement_string(x, file, packages))]
    poetry = data.get("tool", {}).get("poetry", {})
    out += _poetry_table(poetry.get("dependencies"), file, packages)
    out += _poetry_table(poetry.get("dev-dependencies"), file, packages)
    for g in (poetry.get("group", {}) or {}).values():
        out += _poetry_table(g.get("dependencies"), file, packages)
    return out


def parse_setup_py(text: str, file: str, packages: Set[str]) -> List[Spec]:
    strings: List[str] = []
    try:
        tree = ast.parse(text)
        assigns = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                assigns[node.targets[0].id] = node.value

        def collect(v, depth=0):
            if depth > 3 or v is None:
                return
            if isinstance(v, ast.Name):
                collect(assigns.get(v.id), depth + 1)
            elif isinstance(v, (ast.List, ast.Tuple, ast.Set)):
                for e in v.elts:
                    collect(e, depth + 1)
            elif isinstance(v, ast.Dict):
                for e in v.values:
                    collect(e, depth + 1)
            elif isinstance(v, ast.BinOp):
                collect(v.left, depth + 1); collect(v.right, depth + 1)
            elif isinstance(v, ast.Constant) and isinstance(v.value, str):
                strings.append(v.value)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in ("install_requires", "extras_require", "requires", "setup_requires", "tests_require"):
                        collect(kw.value)
    except SyntaxError:
        pass
    out = [s for x in strings if (s := _from_requirement_string(x, file, packages))]
    if not out:   # dynamic setup.py: fall back to quoted requirement strings
        for m in re.finditer(r"[\"']([A-Za-z0-9][A-Za-z0-9_.\-]*\s*(?:\[[^\]]*\])?\s*(?:[<>=!~][^\"']*)?)[\"']", text):
            s = _from_requirement_string(m.group(1), file, packages)
            if s:
                out.append(s)
    return out


def parse_setup_cfg(text: str, file: str, packages: Set[str]) -> List[Spec]:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read_string(text)
    except configparser.Error:
        return []
    lines = []
    if cp.has_option("options", "install_requires"):
        lines += cp.get("options", "install_requires").splitlines()
    if cp.has_section("options.extras_require"):
        for _, v in cp.items("options.extras_require"):
            lines += v.splitlines()
    return [s for x in lines if (s := _from_requirement_string(x.split("#")[0], file, packages))]


def parse_pipfile(text: str, file: str, packages: Set[str]) -> List[Spec]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    out = []
    for sec in ("packages", "dev-packages"):
        for name, val in (data.get(sec) or {}).items():
            if canonicalize_name(name) not in packages:
                continue
            c = val if isinstance(val, str) else (val.get("version", "*") if isinstance(val, dict) else "*")
            spec = SpecifierSet("") if c.strip() == "*" else _specset(c)
            if spec is not None:
                out.append(Spec(file, canonicalize_name(name), f"{name} = {val!r}", [spec]))
    return out


def parse_lock(kind: str, text: str, file: str, packages: Set[str]) -> List[Spec]:
    out = []
    if kind == "pipfile.lock":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        for sec in ("default", "develop"):
            for name, val in (data.get(sec) or {}).items():
                if canonicalize_name(name) in packages and isinstance(val, dict) and str(val.get("version", "")).startswith("=="):
                    out.append(Spec(file, canonicalize_name(name), f"{name} {val['version']}", exact=val["version"][2:]))
        return out
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    for pkg in data.get("package", []) or []:
        if canonicalize_name(pkg.get("name", "")) in packages and pkg.get("version"):
            out.append(Spec(file, canonicalize_name(pkg["name"]), f"{pkg['name']} {pkg['version']}", exact=pkg["version"]))
    return out


def parse_file(path: str, text: str, packages: Iterable[str]) -> List[Spec]:
    pk = {canonicalize_name(p) for p in packages}
    kind = file_kind(path)
    if kind is None or text is None:
        return []
    if kind in LOCK_FILES:
        return parse_lock(kind, text, path, pk)
    return {
        "requirements": parse_requirements,
        "conda": parse_conda,
        "pyproject.toml": parse_pyproject,
        "setup.py": parse_setup_py,
        "setup.cfg": parse_setup_cfg,
        "pipfile": parse_pipfile,
    }[kind](text, path, pk)


def ancestor_dirs(path: str) -> List[str]:
    d = posixpath.dirname(path)
    out = []
    while True:
        out.append(d)
        if d in ("", "/"):
            break
        d = posixpath.dirname(d)
    return out


def candidate_files(source_path: str, tree: Optional[List[str]]) -> Dict[str, List[str]]:
    """Dependency files grouped by the directory they apply to, nearest directory first."""
    dirs = ancestor_dirs(source_path)
    groups: Dict[str, List[str]] = {d: [] for d in dirs}
    if tree is not None:
        for f in tree:
            if file_kind(f) and dep_dir(f) in groups:
                groups[dep_dir(f)].append(f)
    else:
        probe_dirs = dirs[:3] + ([dirs[-1]] if len(dirs) > 3 else [])
        for d in probe_dirs:
            groups[d] = [posixpath.join(d, n) if d else n for n in PROBE_NAMES]
    return {d: fs for d, fs in groups.items() if fs}
