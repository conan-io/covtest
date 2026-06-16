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
    assert parsed.global_calls == {"print": [2]}


def test_parse_globals_defs_annotated_assign():
    """Annotated assignments (x: int = 5, ast.AnnAssign) go into global_objects."""
    src = textwrap.dedent("""\
        x: int = 5
        y = 10
        """)
    parsed = _ParsedFileData(src)
    assert parsed.global_objects == {"x": [1], "y": [2]}
    assert parsed.global_declarations == {}
    assert parsed.global_calls == {}


def test_parse_globals_defs_if_statement():
    """Assignments inside module-level if blocks go into global_objects."""
    src = textwrap.dedent("""\
        if True:
            y = 2
        x = 1
        """)
    parsed = _ParsedFileData(src)
    assert parsed.global_objects == {"y": [2], "x": [3]}
    assert parsed.global_declarations == {}
    assert parsed.global_calls == {}


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
    # declarations record only up to (not including) the first body line
    assert parsed.global_declarations == {"my_func": [1], "MyClass": [4]}
    assert parsed.global_objects == {"x": [7]}
    assert parsed.global_calls == {}


def test_parse_globals_defs_non_name_assign_target():
    """Tuple-unpacking targets are walked to extract individual names."""
    src = textwrap.dedent("""\
        a, b = 1, 2
        x = 10
        """)
    parsed = _ParsedFileData(src)
    assert parsed.global_objects == {"a": [1], "b": [1], "x": [2]}
    assert parsed.global_declarations == {}
    assert parsed.global_calls == {}


def test_global_objects_vs_declarations_separation():
    """Async functions and classes are declarations; assignments are objects; imports appear in neither."""
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
    assert parsed.global_objects == {"CONSTANT": [2], "value": [3]}
    assert parsed.global_declarations == {"sync_fn": [5], "async_fn": [8], "MyClass": [11]}
    assert parsed.global_calls == {}


def test_usage_names_attribute():
    """usage_names tracks only Load contexts (reads), not Store (assignment targets)."""
    src = textwrap.dedent("""\
        x = 1
        y = x + 1
        z = x + y
        """)
    parsed = _ParsedFileData(src)
    assert isinstance(parsed.usage_names, dict)
    # x assigned on line 1 (Store, not tracked), read on lines 2 and 3
    assert parsed.usage_names["x"] == {2, 3}
    # y assigned on line 2 (Store, not tracked), read on line 3
    assert parsed.usage_names["y"] == {3}
    # z is only ever assigned (Store), never read — absent from usage_names
    assert "z" not in parsed.usage_names


def test_usage_names_inside_function_body():
    """Names used inside a function body are tracked at the correct line numbers.
    Function parameters are ast.arg nodes, not ast.Name, so they only appear
    in usage_names when referenced in the body — not at the def line."""
    src = textwrap.dedent("""\
        BASE = 10

        def compute(n):
            result = n + BASE
            return result
        """)
    #                  line 1: BASE assigned (Store, not tracked)
    #                  line 3: n is ast.arg — not an ast.Name node at all
    #                  line 4: n (Load) → tracked, BASE (Load) → tracked, result (Store, not tracked)
    #                  line 5: result (Load) → tracked
    parsed = _ParsedFileData(src)
    assert parsed.usage_names["BASE"] == {4}
    assert parsed.usage_names["n"] == {4}
    assert parsed.usage_names["result"] == {5}


def test_usage_names_inside_class_method():
    """Names referenced inside a class body and nested method bodies are all tracked.
    Demonstrates two levels of nesting (module → class body → method body)."""
    src = textwrap.dedent("""\
        SCALE = 5

        class Scaler:
            base = SCALE * 2

            def apply(self, x):
                return x * SCALE
        """)
    parsed = _ParsedFileData(src)
    assert parsed.usage_names == {"SCALE": {4, 7}, "x": {7}}
    assert parsed.global_objects == {"SCALE": [1]}


def test_usage_names_same_name_across_scopes():
    """A name used at module level, inside a function, and inside a class body
    accumulates all line numbers into a single set — scopes are not separated."""
    src = textwrap.dedent("""\
        count = 0

        def inc():
            x = count + 1
            return x

        class C:
            start = count
        """)
    #   line 1: count assigned (Store, not tracked)
    #   line 4: count (Load) → tracked
    #   line 8: count (Load) → tracked
    parsed = _ParsedFileData(src)
    assert parsed.usage_names["count"] == {4, 8}


def test_usage_names_multiple_names_on_same_line():
    """Several distinct names appearing on a single expression line are each
    recorded with that line in their individual sets."""
    src = textwrap.dedent("""\
        a = 1
        b = 2
        c = 3
        result = a + b + c
        """)
    #   line 4: a (Load), b (Load), c (Load) → tracked; result (Store) → not tracked
    parsed = _ParsedFileData(src)
    for name in ("a", "b", "c"):
        assert 4 in parsed.usage_names[name], f"{name!r} missing line 4"
    assert "result" not in parsed.usage_names


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
