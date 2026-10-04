from pathlib import Path

import pytest

from btw import ast, driver
from btw.ast import Type
from btw.checker import Symbol, SymbolKind, check
from btw.lexer import lex
from btw.parser import parse
from btw.span import Pos, Span

GOLDEN = Path(__file__).parent / "golden"

# Goldens that can't match until another card lands (none right now).
WAITING: dict[str, str] = {}


def run_check(src):
    tokens, comments, _ = lex(src)
    program, _ = parse(tokens, comments)
    symbols, diags = check(program, comments)
    return program, symbols, diags


def wrap(body, top=""):
    """A complete program whose serve block contains `body`."""
    return f"i use arch btw\n{top}serve localhost:3000 {{\n{body}\n}}\n:wq\n"


def short(diags):
    return [f"{d.span.start.line + 1}:{d.span.start.col + 1} {d.code} {d.message}" for d in diags]


def codes(src):
    return [d.code for d in run_check(src)[2]]


def messages(src):
    return [d.message for d in run_check(src)[2]]


@pytest.mark.parametrize(
    "program", sorted(GOLDEN.glob("*.btw")), ids=lambda p: p.stem
)
def test_golden_diagnostics(program, request):
    if program.stem in WAITING:
        request.applymarker(pytest.mark.xfail(reason=WAITING[program.stem], strict=True))
    source = program.read_text(encoding="utf-8")
    _, _, diags = driver.check(source, str(program))
    got = [
        f"{d.span.start.line + 1}:{d.span.start.col + 1}: {d.severity.value}[{d.code}]: {d.message}"
        for d in diags
    ]
    sidecar = program.with_suffix(".diag")
    want = sidecar.read_text(encoding="utf-8") if sidecar.exists() else ""
    assert got == want.splitlines()


def test_valid_program_is_clean():
    src = wrap(
        "npm install i = 0\ndoomscroll i < 3 {\n  git push --force i = add(i, 1)\n}\n"
        "console.log i",
        top="microservice add(a, b) O(1) {\n  ship it a + b\n}\n",
    )
    assert run_check(src)[2] == []


# Symbols and types


def test_fills_sym_and_ty():
    src = wrap(
        "npm install x = LIMIT + 1\nconsole.log f(x) == 2",
        top="npm install -g LIMIT = 10\nmicroservice f(n) O(1) {\n  ship it n\n}\n",
    )
    program, symbols, diags = run_check(src)
    assert diags == []
    limit_decl, f, serve = program.items
    decl, prnt = serve.body.stmts
    limit = symbols.globals["LIMIT"]
    assert limit_decl.name.sym is limit and limit.kind is SymbolKind.CONST
    assert limit.ty is Type.NUMBER and limit.owner == "global"
    assert decl.value.left.sym is limit
    assert decl.value.ty is Type.NUMBER
    x = decl.name.sym
    assert isinstance(x, Symbol) and x.kind is SymbolKind.LOCAL and x.owner == "serve"
    call = prnt.value.left
    assert call.sym is call.callee.sym is f.name.sym is symbols.globals["f"]
    assert call.sym.arity == 1 and call.ty is Type.NUMBER
    assert call.args[0].sym is x
    assert prnt.value.ty is Type.BOOLEAN
    (param,) = f.params
    assert param.sym.kind is SymbolKind.PARAM and param.sym.owner == "f"
    assert f.body.stmts[0].value.sym is param.sym
    assert symbols.frames == {"f": [param.sym], "serve": [x]}


def test_string_keeps_string_type_in_print():
    program, _, diags = run_check(wrap('console.log "hi"'))
    assert diags == []
    assert program.items[0].body.stmts[0].value.ty is Type.STRING


def test_sibling_blocks_get_their_own_symbols():
    src = wrap(
        "vibe check LGTM {\n  npm install i = 1\n  console.log i\n}\nnpm install i = LGTM\nconsole.log i"
    )
    program, symbols, diags = run_check(src)
    assert diags == []
    first, second = symbols.frames["serve"]
    assert first is not second and second.ty is Type.BOOLEAN
    assert program.items[0].body.stmts[2].value.sym is second


def test_error_expr_declares_without_cascade():
    assert codes(wrap("npm install x =\nconsole.log x + 1")) == []


# Structure


def test_e426_spans_line_one():
    (d,) = run_check("serve localhost:3000 {\n}\n:wq\n")[2]
    assert d.code == "E426" and d.span == Span(Pos(0, 0), Pos(1, 0))


def test_e503_without_wq_is_at_end_of_file():
    _, _, diags = run_check("i use arch btw\n")
    (e503,) = [d for d in diags if d.code == "E503"]
    assert e503.span == Span(Pos(1, 0), Pos(1, 0))


def test_e409_extra_serves():
    src = "i use arch btw\n" + "serve localhost:3000 {\n}\n" * 3 + ":wq\n"
    diags = run_check(src)[2]
    assert [(d.code, d.span) for d in diags] == [
        ("E409", Span(Pos(3, 0), Pos(3, 5))),
        ("E409", Span(Pos(5, 0), Pos(5, 5))),
    ]


# Hoisting and names


def test_duplicate_global_and_global_microservice_clash():
    src = wrap(
        "console.log a",
        top="npm install a = 1\nnpm install a = 2\nmicroservice a() {\n}\n",
    )
    assert short(run_check(src)[2]) == [
        "3:13 E409 npm ERR! `a` is already installed. Use `git push --force` to update it.",
        "4:14 E409 npm ERR! `a` is already installed. Use `git push --force` to update it.",
    ]


def test_global_initializer_sees_only_earlier_globals():
    src = wrap("console.log B", top="npm install A = A\nnpm install B = A\n")
    assert messages(src) == [
        "Error 404: variable `A` not found. Did you forget to `npm install` it?"
    ]


def test_global_initializer_microservice_as_value():
    src = wrap("console.log A", top="npm install A = f\nmicroservice f() {\n}\n")
    assert messages(src) == ["`f` is a microservice. Call it: `f(...)`."]


def test_param_shadowing_a_global():
    src = wrap("console.log f(n)", top="npm install n = 1\nmicroservice f(n) {\n}\n")
    assert short(run_check(src)[2]) == [
        "3:16 E409 npm ERR! `n` is already installed. Use `git push --force` to update it."
    ]


def test_local_shadowing_param_and_microservice():
    src = wrap(
        "npm install f = 1",
        top="microservice f(n) {\n  vibe check LGTM {\n    npm install n = 2\n  }\n}\n",
    )
    assert codes(src) == ["E409", "E409"]


def test_redeclared_name_keeps_first_binding():
    src = wrap("npm install x = 1\nnpm install x = LGTM\ngit push --force x = 2")
    assert codes(src) == ["E409"]


def test_use_before_declaration():
    assert codes(wrap("console.log x\nnpm install x = 1")) == ["E404", "W226"]


def test_six_params_fine_seven_monolith():
    six = wrap("console.log f(1, 2, 3, 4, 5, 6)", top="microservice f(a, b, c, d, e, g) {\n}\n")
    assert codes(six) == []
    seven = "microservice f(a, b, c, d, e, g, h) {\n}\n"
    assert codes(wrap("console.log 1", top=seven)) == ["E413"]


def test_assign_to_microservice():
    src = wrap("git push --force f = 1", top="microservice f() {\n}\n")
    assert messages(src) == ["`f` is a microservice. Call it: `f(...)`."]


def test_unknown_assign_target():
    assert codes(wrap("git push --force y = 1")) == ["E404"]


def test_calls_check_arguments_even_when_callee_is_unknown():
    assert codes(wrap("ghost(nope)")) == ["E404", "E404"]


# Types


def test_operator_messages():
    src = wrap(
        "console.log 1 && LGTM\nconsole.log LGTM || 2\nconsole.log LGTM < 404\n"
        "console.log LGTM >= 1\nconsole.log LGTM != 404\nconsole.log 404 * 404"
    )
    assert short(run_check(src)[2]) == [
        "3:13 E418 I'm a teapot: `&&` needs booleans, got a number. "
        "Truthiness is a JavaScript thing.",
        "4:21 E418 I'm a teapot: `||` needs booleans, got a number. "
        "Truthiness is a JavaScript thing.",
        "5:13 E418 I'm a teapot: can't sort booleans with `<`. "
        "LGTM isn't bigger than 404, just more optimistic.",
        "6:13 E418 I'm a teapot: can't compare a number with a boolean.",
        "8:13 E418 I'm a teapot: can't apply `*` to a boolean.",
        "8:19 E418 I'm a teapot: can't apply `*` to a boolean.",
    ]


def test_one_mistake_one_squiggle():
    # The inner error makes `x` UNKNOWN, so nothing around it complains.
    assert codes(wrap("npm install x = ghost\nconsole.log x == LGTM && !x || x < 1")) == ["E404"]
    assert codes(wrap('console.log "a" == LGTM && "b"')) == ["E415", "E415"]


def test_strings_outside_console_log():
    src = wrap(
        'npm install s = "a"\nvibe check "b" {\n}\nship it "c"',
        top='microservice f(n) {\n}\n',
    )
    assert codes(src) == ["E415", "E415", "E415"]
    assert codes(wrap('console.log f("x")', top="microservice f(n) {\n}\n")) == ["E415"]


def test_ship_it_boolean():
    src = wrap("ship it LGTM", top="microservice f() {\n  ship it 404\n}\n")
    assert messages(src) == [
        "I'm a teapot: microservices ship numbers, got a boolean. Ship 1 or 0 like it's 1972.",
        "I'm a teapot: exit codes are numbers, got a boolean. The OS doesn't do code review.",
    ]


def test_wrong_arity_still_checks_argument_types():
    src = wrap("console.log f(LGTM, 1)", top="microservice f(n) {\n}\n")
    assert codes(src) == ["E422", "E418"]


def test_e422_span_is_the_call():
    src = wrap("console.log f()", top="microservice f(n) {\n}\n")
    (d,) = run_check(src)[2]
    assert d.span == Span(Pos(4, 12), Pos(4, 15))


# sudo and loops


def test_e403_span_and_help():
    src = wrap("git push --force   LIMIT = 2", top="npm install -g LIMIT = 1\n")
    (d,) = run_check(src)[2]
    assert d.code == "E403" and d.soft
    assert d.span == Span(Pos(3, 0), Pos(3, 24))
    assert d.help == "try `sudo git push --force LIMIT = ...`"


def test_sudo_on_constant_is_fine():
    src = wrap("sudo git push --force LIMIT = 2", top="npm install -g LIMIT = 1\n")
    assert codes(src) == []


def test_global_flag_in_block_span():
    (d,) = run_check(wrap("npm install -g X = 1"))[2]
    assert d.code == "E405" and d.span == Span(Pos(2, 0), Pos(2, 14))


def test_touch_grass_does_not_leak_into_microservices():
    src = wrap(
        "doomscroll LGTM {\n  console.log f()\n  touch grass\n}",
        top="microservice f() {\n  touch grass\n}\n",
    )
    assert codes(src) == ["E405"]


@pytest.mark.parametrize(
    "body, warns",
    [
        ("console.log 1", True),
        ("touch grass", False),
        ("vibe check LGTM {\n} skill issue {\n  touch grass\n}", False),
        ("vibe check LGTM {\n} skill issue vibe check 404 {\n  touch grass\n}", False),
        ("ship it", False),
        ("doomscroll LGTM {\n  touch grass\n}", True),
        ("doomscroll LGTM {\n  ship it 1\n}", False),
    ],
)
def test_w509(body, warns):
    src = wrap(f"doomscroll LGTM {{\n{body}\n}}")
    diags = [d for d in run_check(src)[2] if d.code == "W509"]
    assert bool(diags) == warns
    if warns:
        assert diags[0].span == Span(Pos(2, 0), Pos(2, 10)) and diags[0].soft


def test_w509_only_for_literal_lgtm():
    assert codes(wrap("doomscroll !404 {\n}")) == []
    assert codes(wrap("doomscroll (LGTM) {\n}")) == ["W509"]


# Comments


def test_comments():
    todos = "".join(f"// TODO {i}\n" for i in range(6))
    src = wrap("console.log 1 // note", top=todos + "// todo lowercase\n")
    assert short(run_check(src)[2]) == [
        "7:1 E429 Error: technical debt limit exceeded (6/5 TODOs). Finish something.",
        "8:1 E406 Error: comments must be `// TODO`. Documentation is a TODO.",
        "10:15 E406 Error: comments must be `// TODO`. Documentation is a TODO.",
    ]


def test_womm_comment_is_not_bad():
    assert codes(wrap("// works on my machine\nconsole.log 1")) == []


def test_ast_node_types_are_filled_everywhere():
    src = wrap(
        "npm install a = -(1 + 2) * 3\nvibe check !(a > 1) || a == 2 {\n  console.log f(a, a % 2)\n}",
        top="microservice f(x, y) O(1) {\n  ship it x / y\n}\n",
    )
    program, _, diags = run_check(src)
    assert diags == []

    def walk(node):
        if isinstance(node, ast.Expr):
            assert node.ty is not None, node
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, ast.Node):
            for value in vars(node).values():
                if isinstance(value, ast.Node | list):
                    walk(value)

    walk(program)


# P2: unnecessary sudo, useless expressions, unreachable code, history


def test_w100():
    src = wrap(
        "npm install x = 1\nsudo git push --force x = 2\nsudo git revert x\n"
        "sudo git push --force C = 2\nsudo git push --force ghost = 1",
        top="npm install -g C = 1\n",
    )
    diags = run_check(src)[2]
    assert [(d.code, d.span) for d in diags] == [
        ("W100", Span(Pos(4, 0), Pos(4, 4))),
        ("W100", Span(Pos(5, 0), Pos(5, 4))),
        ("E404", Span(Pos(7, 22), Pos(7, 27))),
    ]


def test_e403_on_revert():
    (d,) = run_check(wrap("git revert C", top="npm install -g C = 1\n"))[2]
    assert d.code == "E403" and d.help == "try `sudo git revert C`"


def test_w204():
    src = wrap("npm install x = 1\nx\nx + 1\n(f(x))\nf(1) == 0", top="microservice f(n) {\n}\n")
    assert [(d.code, d.span.start.line) for d in run_check(src)[2]] == [
        ("W204", 5),
        ("W204", 6),
        ("W204", 8),
    ]


def test_w410_first_unreachable_statement_per_block():
    src = wrap(
        "vibe check LGTM {\n  ship it 1\n}\nship it 2\nconsole.log 1\nconsole.log 2",
        top="microservice f() {\n  ship it\n  console.log 0\n}\n",
    )
    diags = run_check(src)[2]
    assert [(d.code, d.span.start) for d in diags] == [
        ("W410", Pos(3, 2)),
        ("W410", Pos(10, 0)),
    ]


def test_history_targets():
    src = wrap(
        "npm install s = 1\ngit log s\ngit log G\nvibe check LGTM {\n  npm install b = 1\n"
        "  git revert b\n}\nconsole.log f(1)",
        top="npm install G = 1\nnpm install H = 1\n"
        "microservice f(n) {\n  git log G\n  npm install t = n\n  git log t\n  git revert n\n}\n",
    )
    _, symbols, diags = run_check(src)
    assert [(d.code, d.span) for d in diags] == [
        ("W226", Span(Pos(2, 12), Pos(2, 13))),  # H
        ("E405", Span(Pos(6, 2), Pos(6, 11))),
        ("E405", Span(Pos(7, 2), Pos(7, 14))),
    ]
    tracked = sorted(sym.name for sym in symbols.all if sym.tracked)
    assert tracked == ["G", "b", "s"]


def test_blame_targets_like_log():
    src = wrap(
        "npm install s = 1\ngit blame s\nconsole.log f(1)",
        top="npm install G = 1\nmicroservice f(n) {\n  git blame G\n  git blame n\n  ship it n\n}\n",
    )
    _, symbols, diags = run_check(src)
    assert [(d.code, d.span) for d in diags] == [("E405", Span(Pos(4, 2), Pos(4, 13)))]
    assert sorted(sym.name for sym in symbols.all if sym.tracked) == ["G", "s"]


# P2: unused variables


def test_w226_on_the_name_of_locals_globals_and_constants():
    src = wrap(
        "npm install x = 1\nvibe check LGTM {\n  npm install k = 2\n}",
        top="npm install G = 1\nnpm install -g C = 1\n",
    )
    assert short([d for d in run_check(src)[2] if d.code == "W226"]) == [
        "2:13 W226 226 IM Used: `G` was installed but never used. `npm prune` it.",
        "3:16 W226 226 IM Used: `C` was installed but never used. `npm prune` it.",
        "5:13 W226 226 IM Used: `x` was installed but never used. `npm prune` it.",
        "7:15 W226 226 IM Used: `k` was installed but never used. `npm prune` it.",
    ]


@pytest.mark.parametrize(
    "use",
    [
        "console.log x",
        "git push --force x = 2",
        "git revert x",
        "git log x",
        "git blame x",
        "console.log x(1)",
    ],
    ids=["read", "push", "revert", "log", "blame", "called"],
)
def test_any_mention_is_a_use(use):
    assert "W226" not in codes(wrap(f"npm install x = 1\n{use}"))


def test_parameters_are_exempt():
    assert codes(wrap("console.log f(1)", top="microservice f(n) O(1) {\n}\n")) == []


def test_no_w226_on_a_declaration_with_an_error():
    assert codes(wrap('npm install x = "text"')) == ["E415"]
    assert codes(wrap("npm install x = y")) == ["E404"]


def test_no_w226_in_a_file_with_a_syntax_error():
    src = wrap("npm install x = 2\nif (x > 1) {\n  console.log x\n}")
    assert [d.code for d in driver.check(src, "t.btw")[2]] == ["E400"]


def test_w226_is_suppressible():
    src = wrap("// works on my machine\nnpm install x = 1")
    assert [d.code for d in driver.check(src, "t.btw")[2]] == ["W200"]


# curl (P2)


def test_curl_is_a_number():
    assert short(run_check(wrap("    vibe check curl { }"))[2]) == [
        "3:16 E418 I'm a teapot: `vibe check` needs LGTM or 404, got a number."
    ]


def test_curl_in_a_global_initializer():
    src = wrap("    console.log X + y", top="npm install -g X = 1 + curl\nnpm install y = X\n")
    assert short(run_check(src)[2]) == [
        "2:24 E405 npm ERR! postinstall scripts can't make network calls."
    ]


def test_curl_statement_does_something():
    assert codes(wrap("    curl")) == []


@pytest.mark.parametrize(
    "stmt",
    ["vibe check x === 1 { }", "vibe check x @ 1 { }", "doomscroll x === 1 { }", "vibe check x 1 { }"],
)
def test_condition_cut_short_by_an_error_gets_one_squiggle(stmt):
    src = wrap(f"npm install x = 1\n{stmt}")
    assert [d.code for d in driver.check(src, "t.btw")[2]] == ["E400"]
