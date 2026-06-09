import ast
import os

from covtest.util.files import load


class ParsedData:
    def __init__(self, folder, py_files):
        """Parse only the .py files listed in *py_files* (relative paths, forward-slash
        separated), which are the files that appear in the coverage data."""
        self.files = {}
        for relf in py_files:
            absf = os.path.join(folder, relf.replace("/", os.sep))
            self.files[relf] = _ParsedFileData(load(absf))


class _ParsedFileData:
    """ results of parsing a code file
    """
    def __init__(self, code):
        rootnode = ast.parse(code)
        self.scopes = {}  # Mapping from line to the end line of the current scope (class, function)

        usage_names = {}

        for node in ast.walk(rootnode):
            start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)
            if start is not None:
                end = max(end, self.scopes.get(start, 0))
                if start < end:
                    self.scopes[start] = int(end)
            if isinstance(node, ast.Name):
                usage_names.setdefault(node.id, set()).add(node.lineno)

        self.imports, self.import_sources, self.local_import_sources = self._parse_imports(rootnode)
        self.imports_usages = self._parse_usages(usage_names, self.imports)
        self.global_definitions = self._parse_globals_defs(rootnode)
        self.global_usages = self._parse_usages(usage_names, self.global_definitions)

    @staticmethod
    def _parse_globals_defs(rootnode):
        result = {}

        def _collect(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Assign):
                    for t in child.targets:
                        for name_node in (ast.walk(t) if not isinstance(t, ast.Name) else [t]):
                            if isinstance(name_node, ast.Name):
                                result[name_node.id] = list(range(child.lineno, child.end_lineno+1))
                elif isinstance(child, ast.AnnAssign):
                    if isinstance(child.target, ast.Name):
                        result[child.target.id] = list(range(child.lineno, child.end_lineno+1))
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    pass  # parsed in another place
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    endlineno = child.lineno
                    for n in ast.iter_child_nodes(child):
                        try:
                            endlineno = n.lineno
                            break
                        except AttributeError:
                            pass
                    result[child.name] = list(range(child.lineno, endlineno+1))
                    # Do not recurse into function/class bodies
                else:
                    # Recurse into if/for/while/try/with to find nested assignments
                    _collect(child)

        _collect(rootnode)
        return result

    @staticmethod
    def _parse_imports(rootnode):
        """Return (imports, import_sources, local_import_sources).

        imports:              {imported_name: [lines]}   e.g. "FockSpace" → [5]
        import_sources:       {source_module: [lines]}   e.g. "sympy.physics.quantum.hilbert" → [5]
                              Includes ALL imports (module-level + function-body).
        local_import_sources: {source_module: [lines]}
                              Function-body imports only — imports inside a ``def`` or
                              ``async def`` block.  Used for import-time projection so
                              that only tests which *directly execute* an import statement
                              (not every test in a file that has a module-level import)
                              are projected onto the imported module's lines.
        """
        imports = {}
        import_sources = {}

        # Collect the AST node ids of every Import/ImportFrom that lives inside
        # a function or async-function body.  Using object id() avoids a second
        # full tree walk and is safe because all nodes exist for the lifetime of
        # this call.
        _local_node_ids: set = set()
        for node in ast.walk(rootnode):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        _local_node_ids.add(id(child))

        local_import_sources = {}
        for node in ast.walk(rootnode):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                is_local = id(node) in _local_node_ids
                for alias in node.names:
                    # from X.Y import Z  →  src="X.Y", name="Z"
                    # import X.Y         →  src="X.Y", name="X.Y"
                    src = node.module if isinstance(node, ast.ImportFrom) else alias.name
                    for line in range(node.lineno, node.end_lineno + 1):
                        imports.setdefault(alias.name, []).append(line)
                        if src:  # None only for bare relative: "from . import X"
                            import_sources.setdefault(src, []).append(line)
                            if is_local:
                                local_import_sources.setdefault(src, []).append(line)
        return imports, import_sources, local_import_sources

    @staticmethod
    def _parse_usages(usage_names, defs):
        result = {}
        for name, lines in defs.items():
            existing = usage_names.get(name)
            if existing:
                # FIXME: This existing might be broken, might need to accumulate
                result[name] = existing
        return result
