import textwrap

from covtest.ast_parser import _ParsedFileData


def test_parse_globals_defs_bare_expression():
    """Module-level bare expressions (ast.Expr) have no .name — must not raise."""
    src = textwrap.dedent("""\
        "module docstring"
        print("hello")
        x = 1
        """)
    parsed = _ParsedFileData(src)
    assert "x" in parsed.global_definitions


def test_parse_globals_defs_annotated_assign():
    """Annotated assignments (x: int = 5, ast.AnnAssign) have no .name — must not raise."""
    src = textwrap.dedent("""\
        x: int = 5
        y = 10
        """)
    parsed = _ParsedFileData(src)
    assert "y" in parsed.global_definitions
    assert "x" in parsed.global_definitions


def test_parse_globals_defs_if_statement():
    """Module-level if/for/try blocks have no .name — must not raise."""
    src = textwrap.dedent("""\
        if True:
            y = 2
        x = 1
        """)
    parsed = _ParsedFileData(src)
    assert "x" in parsed.global_definitions
    assert "y" in parsed.global_definitions


def test_parse_globals_defs_functions_and_classes():
    """FunctionDef and ClassDef must still be captured as global definitions."""
    src = textwrap.dedent("""\
        def my_func():
            pass

        class MyClass:
            pass

        x = 1
        """)
    parsed = _ParsedFileData(src)
    assert "my_func" in parsed.global_definitions
    assert "MyClass" in parsed.global_definitions
    assert "x" in parsed.global_definitions


def test_parse_globals_defs_non_name_assign_target():
    """_ParsedFileData must not raise when a module-level assignment has a target
    without an '.id' attribute (e.g. tuple unpacking, subscript, attribute).
    Without the try/except around t.id in _parse_globals_defs, parsing such
    code would raise AttributeError.
    """
    src = textwrap.dedent("""\
        a, b = 1, 2
        x = 10
        """)
    parsed = _ParsedFileData(src)
    assert "x" in parsed.global_definitions
    assert "a" in parsed.global_definitions
    assert "b" in parsed.global_definitions


def test_parse_imports_local():
    """Imports inside a function body must appear in both imports and import_sources."""
    src = textwrap.dedent("""\
        from someglobal.somemodule import something
        
        def test_foo():
            from mypackage.mymodule import MyClass
            assert MyClass()

        def test_bar():
            import another.module
            another.module.do_something()
        """)
    parsed = _ParsedFileData(src)
    # imports: the imported *name*
    assert parsed.imports == {'MyClass': [4], 'another.module': [8], 'something': [1]}
    # import_sources: the *source module path*
    assert parsed.import_sources == {'another.module': [8], 'mypackage.mymodule': [4], 'someglobal.somemodule': [1]}


def test_python_parsed_scopes():
    src = textwrap.dedent("""\
        def myfunc():
            a = 3
            b = 2
            # some comment
            c = 1
            if a == 3:
                b = 4
                # comment
                if b == 8:
                    pass # other scope
                c = 5

            c = 5

        def otherfunc():
            pass
        """)
    parsed = _ParsedFileData(src)
    print(parsed.scopes)
    result = []
    read_lines = src.splitlines()
    for line, tests in sorted(parsed.scopes.items()):
        result.append(f"   {line:<2}: {read_lines[line - 1][:49]:<50} -> {tests}")
    print("\n".join(result))
