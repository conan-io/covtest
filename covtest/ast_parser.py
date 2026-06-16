import ast
import os

from covtest.util.files import load


def _resolve_relative_dotpath(relf, level, module):
    """Resolve a relative import to an absolute dotpath given the importing file's rel_path.

    Examples::

        _resolve_relative_dotpath("mypkg/__init__.py", 1, "sub")   → "mypkg.sub"
        _resolve_relative_dotpath("mypkg/foo.py",      1, "bar")   → "mypkg.bar"
        _resolve_relative_dotpath("a/b/__init__.py",   2, "utils") → "a.utils"
        _resolve_relative_dotpath("mypkg/__init__.py", 1, None)    → "mypkg"  (bare from . import X)
    """
    relf = relf.replace("\\", "/")
    if relf.endswith("/__init__.py"):
        package = relf[: -len("/__init__.py")].replace("/", ".")
    elif "/" in relf:
        package = relf.rsplit("/", 1)[0].replace("/", ".")
    else:
        package = ""

    parts = package.split(".") if package else []
    base_parts = parts[: len(parts) - (level - 1)] if level > 1 else parts
    base = ".".join(base_parts)

    if module:
        return f"{base}.{module}" if base else module
    return base or None


class ParsedData:
    def __init__(self, folder, py_files):
        """Parse only the .py files listed in *py_files* (relative paths, forward-slash
        separated), which are the files that appear in the coverage data."""
        self.files = {}
        for relf in py_files:
            absf = os.path.join(folder, relf.replace("/", os.sep))
            self.files[relf] = _ParsedFileData(load(absf), relf)


class _ParsedFileData:
    """ results of parsing a code file
    """
    def __init__(self, code, relf=""):
        rootnode = ast.parse(code)
        self.scopes = {}  # Mapping from line to the end line of the current scope (class, function)

        self.usage_names = {}

        for node in ast.walk(rootnode):
            start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)
            if start is not None:
                end = max(end, self.scopes.get(start, 0))
                if start < end:
                    self.scopes[start] = int(end)
            if isinstance(node, ast.Name):
                self.usage_names.setdefault(node.id, set()).add(node.lineno)

        self.imports, self.import_sources = self._parse_imports(rootnode, relf)
        self.imports_usages = self._parse_usages(self.usage_names, self.imports)
        self.global_objects, self.global_declarations, self.global_calls = self._parse_globals_defs(rootnode)
        all_globals = {**self.global_objects, **self.global_declarations}
        self.global_usages = self._parse_usages(self.usage_names, all_globals)

    @staticmethod
    def _parse_globals_defs(rootnode):
        """Return (global_objects, global_declarations, global_calls).

        global_objects:      module-level variables, assignments, and annotated assignments —
                             things that *execute* (run code) when the module is imported.
        global_declarations: function and class definitions — things that only register
                             a name at import time without executing their bodies.
        global_calls:        module-level bare function calls not assigned to a name,
                             e.g. ``compute()``; maps called name → lines.
        """
        objects = {}
        declarations = {}
        calls = {}

        def _collect(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Assign):
                    for t in child.targets:
                        for name_node in (ast.walk(t) if not isinstance(t, ast.Name) else [t]):
                            if isinstance(name_node, ast.Name):
                                objects[name_node.id] = list(range(child.lineno, child.end_lineno+1))
                elif isinstance(child, ast.AnnAssign):
                    if isinstance(child.target, ast.Name):
                        objects[child.target.id] = list(range(child.lineno, child.end_lineno+1))
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    pass  # parsed in another place
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    body_start = child.body[0].lineno if child.body else child.end_lineno + 1
                    declarations[child.name] = list(range(child.lineno, body_start))
                    # Do not recurse into function/class bodies
                elif isinstance(child, ast.Expr):
                    if isinstance(child.value, ast.Call) and isinstance(child.value.func, ast.Name):
                        calls[child.value.func.id] = list(range(child.lineno, child.end_lineno + 1))
                else:
                    # Recurse into if/for/while/try/with to find nested assignments
                    _collect(child)

        _collect(rootnode)
        return objects, declarations, calls

    @staticmethod
    def _parse_imports(rootnode, relf=""):
        """Return (imports, import_sources).

        imports:        {imported_name: [lines]}   e.g. "FockSpace" → [5]
        import_sources: {source_module: [lines]}   e.g. "sympy.physics.quantum.hilbert" → [5]
                        Includes ALL imports (module-level + function-body).
                        Relative imports are resolved to absolute dotpaths using relf.
        """
        imports = {}
        import_sources = {}

        for node in ast.walk(rootnode):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                for alias in node.names:
                    if isinstance(node, ast.ImportFrom):
                        if node.level > 0:
                            mod = node.module or alias.name
                            src = _resolve_relative_dotpath(relf, node.level, mod) if relf else None
                        else:
                            src = node.module
                    else:
                        src = alias.name
                    for line in range(node.lineno, node.end_lineno + 1):
                        imports.setdefault(alias.name, []).append(line)
                        if src:
                            import_sources.setdefault(src, []).append(line)
        return imports, import_sources

    @staticmethod
    def _parse_usages(usage_names, defs):
        result = {}
        for name, lines in defs.items():
            existing = usage_names.get(name)
            if existing:
                # FIXME: This existing might be broken, might need to accumulate
                result[name] = existing
        return result
