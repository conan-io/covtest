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
        # Mapping from line to the end line of the current scope (class, function)
        self.scopes, self.usage_names = self._get_usages(rootnode)
        self.imports, self.import_sources, self.import_bindings = self._parse_imports(rootnode, relf)
        self.imports_usages = self._parse_usages(self.usage_names, self.imports)
        self.global_objects, self.global_declarations, self.global_calls = self._parse_globals_defs(rootnode)
        all_globals = {**self.global_objects, **self.global_declarations}
        self.global_usages = self._parse_usages(self.usage_names, all_globals)

    @staticmethod
    def _get_usages(rootnode):
        usage_names = {}
        scopes = {}
        for node in ast.walk(rootnode):
            start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)
            if start is not None:
                end = max(end, scopes.get(start, 0))
                if start < end:
                    scopes[start] = int(end)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                usage_names.setdefault(node.id, set()).add(node.lineno)
        return scopes, usage_names

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
        """Return (imports, import_sources, import_bindings).

        imports:        {imported_name: [lines]}   e.g. "FockSpace" → [5]
        import_sources: {source_module: [lines]}   e.g. "sympy.physics.quantum.hilbert" → [5]
                        Includes ALL imports (module-level + function-body).
                        Relative imports are resolved to absolute dotpaths using relf.
        import_bindings: {bound_name: (dotpath, original_name, is_module_import, lines, sole_name)}
                        One entry per name bound into the local namespace, keyed by the bound
                        name (the alias if ``as`` is used, else the imported name).  Used by the
                        cross-file projection to resolve each name to its source module and the
                        original name defined there.
                          - dotpath: source module dotpath (resolved for relative imports)
                          - original_name: the name as defined in the source module
                          - is_module_import: True for ``import M`` / ``import a.b`` (whole module)
                          - lines: line range of the import statement
                          - sole_name: True iff the statement binds exactly one name (enables the
                            re-export rule without multi-name contamination)
        """
        imports = {}
        import_sources = {}
        import_bindings = {}

        for node in ast.walk(rootnode):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                lines = list(range(node.lineno, node.end_lineno + 1))
                sole_name = len(node.names) == 1
                for alias in node.names:
                    is_module = isinstance(node, ast.Import)
                    if isinstance(node, ast.ImportFrom):
                        if node.level > 0:
                            mod = node.module or alias.name
                            src = _resolve_relative_dotpath(relf, node.level, mod) if relf else None
                        else:
                            src = node.module
                        original_name = alias.name
                    else:
                        # "import a.b.c" binds the top name "a"; "import a.b as c" binds "c".
                        src = alias.name
                        original_name = alias.name
                    bound_name = alias.asname or (alias.name.split(".")[0] if is_module else alias.name)
                    for line in lines:
                        imports.setdefault(alias.name, []).append(line)
                        if src:
                            import_sources.setdefault(src, []).append(line)
                    if src:
                        import_bindings[bound_name] = (src, original_name, is_module, lines, sole_name)
        return imports, import_sources, import_bindings

    @staticmethod
    def _parse_usages(usage_names, defs):
        result = {}
        for name, lines in defs.items():
            existing = usage_names.get(name)
            if existing:
                # FIXME: This existing might be broken, might need to accumulate
                result[name] = existing
        return result
