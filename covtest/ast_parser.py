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
                self.files[relf] = ParsedFileData(load(absf))

    def line_mappings(self):
        result = {}
        # print("-------------------LINE MAPPINGS---------------------------")
        for file, parsed_data in self.files.items():
            # print("PROCESSING FILE ", file)
            file_mapping = {}
            result[file] = file_mapping
            for scope in parsed_data.scopes.values():
                for line in scope[1:]:
                    file_mapping[line] = {file: [scope[0]]}
            for key, (sources, targets) in parsed_data.global_usages.items():
                for line in sources:
                    file_mapping.setdefault(line, {}).setdefault(file, []).extend(targets)

            for import_name, lines in parsed_data.imports_usages.items():
                # print("     Processing IMPORT=", import_name, lines)
                sources, targets = lines
                # print("     Sources", sources, targets)
                #for line in sources:
                #    file_mapping.setdefault(line, {}).setdefault(file, []).extend(targets)
                # TODO: bad approximation, just look for the name in all files, and alias == name
                for other_file, other_data in self.files.items():
                    # print("         Other file", other_file)
                    lines_found = other_data.global_declarations.get(import_name)
                    # print("         Lines found", lines_found)
                    if not lines_found:
                        continue
                    for line in sources:
                        # print("            Adding mapping", line, "->", other_file, ":", lines_found)
                        file_mapping.setdefault(line, {}).setdefault(other_file, []).extend(lines_found)
                    global_usages = other_data.global_usages.get(import_name)
                    if global_usages is None:
                        # print("       No global usage of ")
                        continue
                    other_sources, other_targets = global_usages
                    # print("         Found other global ", other_sources, other_targets)
                    for line in sources:
                        # print("           Adding glogal mapping", line, "->", other_file, ":", other_targets)
                        file_mapping.setdefault(line, {}).setdefault(other_file, []).extend(other_targets)
                        # repeat expansion of globals from targets
                        for rec_key, (rec_sources, rec_targets) in other_data.global_usages.items():
                            # print("           Recursing global usage ", rec_key, rec_sources, rec_targets)
                            # print("           CHekcing if ", other_targets, "intersects", rec_sources)
                            if set(other_targets).intersection(rec_sources):
                                file_mapping.setdefault(line, {}).setdefault(other_file, []).extend(rec_targets)
        return result


class ParsedFileData:
    """ results of parsing a code file
    """
    def __init__(self, code):
        rootnode = ast.parse(code)
        self.scopes = {}  # Mapping from line to the end line of the current scope (class, function)
        for node in ast.walk(rootnode):
            start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)
            if start is not None:
                self.scopes[start] = max(end, self.scopes.get(start, 0))

        self.imports = _parse_imports(rootnode)
        self.imports_usages = _parse_usages(rootnode, self.imports)
        self.global_definitions = _parse_globals_defs(rootnode)
        self.global_usages = _parse_usages(rootnode, self.global_definitions)


def _parse_globals_defs(rootnode):
    result = {}
    for child in ast.iter_child_nodes(rootnode):
        if isinstance(child, ast.Assign):
            for t in child.targets:
                result[t.id] = list(range(child.lineno, child.end_lineno+1))
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            pass  # parsed in another place
        else:
            endlineno = child.lineno
            for n in ast.iter_child_nodes(child):
                try:
                    endlineno = n.lineno
                    break
                except:
                    pass
            try:
                result[child.name] = list(range(child.lineno, endlineno+1))
            except Exception as e:
                print("Couldn't parse global ", str(e))

    return result


def _parse_imports(rootnode):
    # TODO: Check what happens with nested imports and try-except imports
    result = {}
    for child in ast.iter_child_nodes(rootnode):
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                for line in range(child.lineno, child.end_lineno+1):
                    result.setdefault(alias.name, []).append(line)
    return result


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
