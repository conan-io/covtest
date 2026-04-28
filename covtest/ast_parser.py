import ast
import logging
import os

from covtest.util.files import load

logger = logging.getLogger(__name__)


class ParsedData:
    def __init__(self, folder):
        self.files = {}
        for root, dirs, files in os.walk(folder):
            for f in files:
                if not f.endswith(".py"):
                    continue
                absf = os.path.join(root, f)
                relf = os.path.relpath(absf, folder).replace("\\", "/")
                self.files[relf] = _ParsedFileData(load(absf))


class _ParsedFileData:
    """ results of parsing a code file
    """
    def __init__(self, code):
        rootnode = ast.parse(code)
        self.scopes = {}  # Mapping from line to the end line of the current scope (class, function)
        for node in ast.walk(rootnode):
            start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)
            if start is not None:
                self.scopes[start] = max(end, self.scopes.get(start, 0))

        self.imports = self._parse_imports(rootnode)
        self.imports_usages = self._parse_usages(rootnode, self.imports)
        self.global_definitions = self._parse_globals_defs(rootnode)
        self.global_usages = self._parse_usages(rootnode, self.global_definitions)

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
        # TODO: Check what happens with nested imports and try-except imports
        result = {}
        for child in ast.iter_child_nodes(rootnode):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    for line in range(child.lineno, child.end_lineno+1):
                        result.setdefault(alias.name, []).append(line)
        return result

    @staticmethod
    def _parse_usages(rootnode, defs):

        class MyVisitor(ast.NodeVisitor):
            names = {}

            def generic_visit(self, node):
                ast.NodeVisitor.generic_visit(self, node)

            def visit_Name(self, node):
                self.names.setdefault(node.id, set()).add(node.lineno)

        visitor = MyVisitor()
        visitor.visit(rootnode)
        usage_names = visitor.names

        result = {}
        for name, lines in defs.items():
            existing = usage_names.get(name)
            if existing:
                # FIXME: This existing might be broken, might need to accumulate
                result[name] = existing
        return result
