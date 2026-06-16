import textwrap

from covtest.ast_parser import _ParsedFileData  # noqa


def test_parse_globals_defs_bare_expression():
    """Module-level bare expressions (ast.Expr) have no .name — must not raise."""
    src = textwrap.dedent("""\
        "module docstring"
        print("hello")
        x = 1
        """)
    parsed = _ParsedFileData(src)
    assert parsed.global_objects == {"x": [3]}
    assert parsed.global_declarations == {}


def test_parse_globals_defs_annotated_assign():
    """Annotated assignments (x: int = 5, ast.AnnAssign) go into global_objects."""
    src = textwrap.dedent("""\
        x: int = 5
        y = 10
        """)
    parsed = _ParsedFileData(src)
    assert "y" in parsed.global_objects
    assert "x" in parsed.global_objects


def test_parse_globals_defs_if_statement():
    """Assignments inside module-level if blocks go into global_objects."""
    src = textwrap.dedent("""\
        if True:
            y = 2
        x = 1
        """)
    parsed = _ParsedFileData(src)
    assert "x" in parsed.global_objects
    assert "y" in parsed.global_objects


def test_parse_globals_function_call():
    """Module-level bare expressions (ast.Expr) have no .name — must not raise."""
    src = textwrap.dedent("""\
        def compute():
            a  = 3
            
        compute()
        """)
    parsed = _ParsedFileData(src)
    assert parsed.global_calls == {"compute": [4]}
    assert parsed.global_declarations == {"compute": [1]}


def test_parse_globals_defs_functions_and_classes():
    """FunctionDef and ClassDef land in global_declarations; plain assignments in global_objects."""
    src = textwrap.dedent("""\
        def my_func():
            pass

        class MyClass:
            pass

        x = 1
        """)
    parsed = _ParsedFileData(src)
    assert "my_func" in parsed.global_declarations
    assert "MyClass" in parsed.global_declarations
    assert "x" in parsed.global_objects
    # No cross-contamination
    assert "my_func" not in parsed.global_objects
    assert "MyClass" not in parsed.global_objects
    assert "x" not in parsed.global_declarations


def test_parse_globals_defs_non_name_assign_target():
    """_ParsedFileData must not raise when a module-level assignment has a target
    without an '.id' attribute (e.g. tuple unpacking, subscript, attribute).
    """
    src = textwrap.dedent("""\
        a, b = 1, 2
        x = 10
        """)
    parsed = _ParsedFileData(src)
    assert "x" in parsed.global_objects
    assert "a" in parsed.global_objects
    assert "b" in parsed.global_objects


def test_global_objects_vs_declarations_separation():
    """Async functions and classes are declarations; assignments are objects."""
    src = textwrap.dedent("""\
        import os
        CONSTANT = 42
        value: int = 5

        def sync_fn():
            pass

        async def async_fn():
            pass

        class MyClass:
            pass
        """)
    parsed = _ParsedFileData(src)
    assert "CONSTANT" in parsed.global_objects
    assert "value" in parsed.global_objects
    assert "sync_fn" in parsed.global_declarations
    assert "async_fn" in parsed.global_declarations
    assert "MyClass" in parsed.global_declarations
    assert "CONSTANT" not in parsed.global_declarations
    assert "sync_fn" not in parsed.global_objects


def test_usage_names_attribute():
    """usage_names is a public attribute mapping name → set of line numbers."""
    src = textwrap.dedent("""\
        x = 1
        y = x + 1
        z = x + y
        """)
    parsed = _ParsedFileData(src)
    assert isinstance(parsed.usage_names, dict)
    assert 2 in parsed.usage_names["x"]
    assert 3 in parsed.usage_names["x"]
    assert 3 in parsed.usage_names["y"]


def test_parse_imports_local():
    """All imports appear in imports and import_sources regardless of scope.
    local_import_sources is no longer tracked."""
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
    assert parsed.imports == {'MyClass': [4], 'another.module': [8], 'something': [1]}
    assert parsed.import_sources == {'another.module': [8], 'mypackage.mymodule': [4], 'someglobal.somemodule': [1]}
    assert not hasattr(parsed, 'local_import_sources')


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
    assert parsed.scopes == {1: 13, 15: 16, 6: 11, 9: 10}
