from pathlib import Path

import pytest

from btw import ast
from btw.lexer import lex
from btw.diagnostics import Diagnostic, Edit, Fix, Severity
from btw.parser import W208, format_ast, parse
from btw.span import Pos, Span
from btw.tokens import Token, TokenKind as K

GOLDEN = Path(__file__).parent / "golden"
LISP = " Even Lisp programmers close their parentheses."

def parse_src(src):
    tokens, comments, lex_diags = lex(src)
    program, diags = parse(tokens, comments)
    return program, lex_diags, diags


def wrap(body):
    """A complete program whose serve block contains `body`."""
    return f"i use arch btw\nserve localhost:3000 {{\n{body}\n}}\n:wq\n"


def stmts(body):
    program, _, diags = parse_src(wrap(body))
    assert diags == [], diags
    return program.items[0].body.stmts


def expr(text):
    (stmt,) = stmts(f"console.log {text}")
    return stmt.value


def errors(src):
    """Parser diagnostics as (1-based line, col, code, message)."""
    _, _, diags = parse_src(src)
    return [(d.span.start.line + 1, d.span.start.col + 1, d.code, d.message) for d in diags]


def sexp(e):
    """A compact rendering of an expression tree."""
    match e:
        case ast.Binary(op=op, left=left, right=right):
            return f"({sexp(left)} {op} {sexp(right)})"
        case ast.Unary(op=op, operand=operand):
            return f"({op}{sexp(operand)})"
        case ast.Call(callee=callee, args=args):
            return f"{callee.name}({', '.join(sexp(a) for a in args)})"
        case ast.IntLit(value=v):
            return str(v)
        case ast.BoolLit(value=v):
            return "LGTM" if v else "404"
        case ast.StrLit(value=v):
            return repr(v)
        case ast.Var(name=name):
            return name
        case ast.ErrorExpr():
            return "<error>"
    raise AssertionError(e)


def sp(l1, c1, l2, c2):
    """A span from 1-based positions."""
    return Span(Pos(l1 - 1, c1 - 1), Pos(l2 - 1, c2 - 1))


# Program shape


def test_hello_world():
    program, _, diags = parse_src(wrap('    console.log "hi"'))
    assert diags == []
    assert program.has_arch
    assert program.wq_span == sp(5, 1, 5, 4)
    assert program.trailing_span is None
    (serve,) = program.items
    assert isinstance(serve, ast.Serve) and serve.port == 3000
    (stmt,) = serve.body.stmts
    assert stmt == ast.Print(ast.StrLit("hi", span=sp(3, 17, 3, 21)), span=sp(3, 5, 3, 21))


def test_top_level_items_in_any_order():
    src = (
        "i use arch btw\n"
        "serve localhost:3000 { console.log f(LIMIT) }\n"
        "microservice f(n) O(1) { ship it n }\n"
        "npm install -g LIMIT = 10\n"
        "npm install count = LIMIT + 1\n"
        ":wq\n"
    )
    program, _, diags = parse_src(src)
    assert diags == []
    assert [type(i).__name__ for i in program.items] == [
        "Serve",
        "Microservice",
        "GlobalDecl",
        "GlobalDecl",
    ]
    assert program.items[2].is_const and not program.items[3].is_const


def test_items_need_no_newline_between_them():
    program, _, diags = parse_src("i use arch btw serve localhost:3000 { } :wq")
    assert diags == []
    assert program.has_arch and len(program.items) == 1 and program.wq_span is not None


def test_comments_are_kept():
    program, _, _ = parse_src("// TODO later\n" + wrap("    touch grass // TODO x"))
    assert [c.text for c in program.comments] == ["// TODO later", "// TODO x"]


def test_missing_arch_is_recorded_not_reported():
    program, _, diags = parse_src("\nserve localhost:3000 { }\n:wq\n")
    assert diags == []
    assert not program.has_arch
    assert len(program.items) == 1


def test_leading_newlines_before_arch():
    program, _, diags = parse_src("\n\ni use arch btw\nserve localhost:3000 { }\n:wq\n")
    assert program.has_arch and diags == []


def test_repeated_arch_line_is_w208_on_each_repeat():
    program, _, diags = parse_src("i use arch btw\ni use arch btw\n" + wrap("  i use   arch btw"))
    assert program.has_arch
    assert program.items[0].body.stmts == []
    assert diags == [
        Diagnostic("W208", Severity.WARNING, W208, sp(2, 1, 2, 15), soft=True),
        Diagnostic("W208", Severity.WARNING, W208, sp(3, 1, 3, 15), soft=True),
        Diagnostic("W208", Severity.WARNING, W208, sp(5, 3, 5, 19), soft=True),
    ]


def test_one_misplaced_arch_line_is_not_a_repeat():
    # Not first, so has_arch is false (E426, the checker's), but not a second one either.
    program, _, diags = parse_src("serve localhost:3000 { }\ni use arch btw\n:wq\n")
    assert not program.has_arch and diags == []


def test_arch_line_after_wq_is_only_trailing():
    program, _, diags = parse_src(wrap("") + "i use arch btw\n")
    assert diags == [] and program.trailing_span == sp(6, 1, 7, 1)


def test_trailing_tokens_are_recorded_not_reported():
    program, _, diags = parse_src(wrap("") + 'console.log "after"\n\n')
    assert diags == []
    assert program.wq_span == sp(5, 1, 5, 4)
    # From the first token after `:wq` to the end of the file.
    assert program.trailing_span == sp(6, 1, 8, 1)


def test_newlines_after_wq_are_not_trailing():
    program, _, _ = parse_src(wrap("") + "\n\n")
    assert program.trailing_span is None


def test_missing_wq_is_e408_on_last_real_token():
    src = 'i use arch btw\nserve localhost:3000 {\n    console.log "no exit"\n}\n\n'
    program, _, _ = parse_src(src)
    assert program.wq_span is None
    assert errors(src) == [(4, 1, "E408", "Error: program never exited. Classic Vim user.")]


def test_missing_wq_in_empty_file_is_on_eof():
    _, _, diags = parse_src("")
    (d,) = diags
    assert d.code == "E408" and d.span == Span(Pos(0, 0), Pos(0, 0))


def test_wq_inside_unclosed_block_still_ends_the_program():
    src = "i use arch btw\nserve localhost:3000 {\n    console.log 1\n:wq\n"
    program, _, _ = parse_src(src)
    assert program.wq_span == sp(4, 1, 4, 4)
    assert errors(src) == [(4, 1, "E400", "Syntax error: expected `}`, found `:wq`.")]


def test_wq_in_skipped_top_level_junk_still_counts():
    program, _, _ = parse_src("i use arch btw\nserve localhost:3000 { }\n} } :wq\n")
    assert program.wq_span == sp(3, 5, 3, 8)


# Blocks and statements


def test_one_line_blocks():
    (loop,) = stmts('doomscroll LGTM { console.log "x" }')
    assert isinstance(loop, ast.While)
    assert [type(s).__name__ for s in loop.body.stmts] == ["Print"]


def test_empty_blocks():
    (if_,) = stmts("vibe check LGTM { } skill issue {\n\n}")
    assert if_.then.stmts == [] and if_.else_.stmts == []


def test_skill_issue_on_the_line_after_the_brace():
    (if_,) = stmts("vibe check LGTM {\n} \n\n skill issue {\n console.log 1\n}")
    assert isinstance(if_.else_, ast.Block)
    assert len(if_.else_.stmts) == 1


def test_skill_issue_on_the_same_line():
    (if_,) = stmts("vibe check LGTM { touch grass } skill issue { touch grass }")
    assert isinstance(if_.else_, ast.Block)


def test_else_if_chain():
    body = (
        "vibe check n < 10 { console.log 1 }\n"
        "skill issue vibe check n < 20 { console.log 2 }\n"
        "skill issue { console.log 3 }\n"
        "console.log 4"
    )
    first, last = stmts(body)
    assert isinstance(first.else_, ast.If)
    assert isinstance(first.else_.else_, ast.Block)
    assert first.span == sp(3, 1, 5, 30)
    assert isinstance(last, ast.Print)


def test_no_else_leaves_the_newlines():
    first, second = stmts("vibe check LGTM { }\n\nconsole.log 1")
    assert first.else_ is None and isinstance(second, ast.Print)


def test_fizzbuzz_shape():
    program, _, diags = parse_src((GOLDEN / "p0_fizzbuzz.btw").read_text())
    assert diags == []
    decl, loop = program.items[0].body.stmts
    chain, push = loop.body.stmts
    depth = 0
    node = chain
    while isinstance(node, ast.If):
        depth += 1
        node = node.else_
    assert depth == 3 and isinstance(node, ast.Block)
    assert isinstance(push, ast.Assign)


def test_optional_parens_around_conditions():
    with_parens, bare = stmts("vibe check (x == 1) { }\nvibe check x == 1 { }")
    assert sexp(with_parens.cond) == sexp(bare.cond) == "(x == 1)"
    # The parens make no node: the condition keeps its own span.
    assert with_parens.cond.span == sp(3, 13, 3, 19)


def test_while_condition_parens():
    (loop,) = stmts("doomscroll (x < 3) { git push --force x = x + 1 }")
    assert sexp(loop.cond) == "(x < 3)"


def test_ship_it_with_and_without_value():
    a, b, c = stmts("ship it\nship it 1 + 2\nvibe check LGTM { ship it }")
    assert a.value is None and a.span == sp(3, 1, 3, 8)
    assert sexp(b.value) == "(1 + 2)"
    assert c.then.stmts[0].value is None


def test_ship_it_at_end_of_file():
    program, _, _ = parse_src("i use arch btw\nmicroservice f() {\n ship it")
    assert program.items[0].body.stmts[0].value is None


def test_declarations_and_assignments():
    a, b, c, d = stmts(
        "npm install x = 1\n"
        "npm install -g Y = 2\n"
        "git push --force x = 3\n"
        "sudo git push --force Y = 4"
    )
    assert isinstance(a, ast.VarDecl) and not a.is_const and a.name.name == "x"
    assert isinstance(b, ast.VarDecl) and b.is_const
    assert isinstance(c, ast.Assign) and not c.sudo
    assert c.name == ast.Var("x", span=sp(5, 18, 5, 19))
    assert isinstance(d, ast.Assign) and d.sudo and d.span.start == Pos(5, 0)


def test_history_statements():
    a, b, c = stmts("git revert x\nsudo git revert X\ngit log x")
    assert isinstance(a, ast.Revert) and not a.sudo
    assert isinstance(b, ast.Revert) and b.sudo and b.span == sp(4, 1, 4, 18)
    assert isinstance(c, ast.Log) and c.name.name == "x"


def test_break_and_expression_statements():
    a, b = stmts("touch grass\nf(1, 2)")
    assert isinstance(a, ast.Break)
    assert isinstance(b, ast.ExprStmt) and sexp(b.expr) == "f(1, 2)"


def test_multi_word_keywords_with_extra_spaces():
    (if_,) = stmts("vibe   check LGTM { ship\tit }  skill  issue { }")
    assert isinstance(if_.then.stmts[0], ast.Return) and if_.else_ is not None


# Microservices and Big O


def micro(header):
    program, _, diags = parse_src(f"i use arch btw\nmicroservice {header} {{ ship it 0 }}\n:wq\n")
    assert [d for d in diags if d.code == "E400"] == []
    return program.items[0]


def test_microservice_params():
    m = micro("f(a, b, c)")
    assert m.name == ast.Ident("f", span=sp(2, 14, 2, 15))
    assert [p.name for p in m.params] == ["a", "b", "c"]
    assert micro("g()").params == []
    assert micro("g()").big_o is None


@pytest.mark.parametrize(
    "annotation, degree, var, text",
    [
        ("O(1)", 0, None, "1"),
        ("O(n)", 1, "n", "n"),
        ("O(items)", 1, "items", "items"),
        ("O(n^2)", 2, "n", "n^2"),
        ("O(m^3)", 3, "m", "m^3"),
        ("O(n ^ 4)", 4, "n", "n ^ 4"),
        ("O(log n)", None, None, "log n"),
        ("O(n log n)", None, None, "n log n"),
        ("O(2^n)", None, None, "2^n"),
        ("O(n!)", None, None, "n!"),
        ("O( log  n )", None, None, " log  n "),
        ("O(2)", None, None, "2"),
        ("O()", None, None, ""),
        ("O(f(n))", None, None, "f(n)"),
    ],
)
def test_big_o_forms(annotation, degree, var, text):
    big_o = micro(f"f(n) {annotation}").big_o
    assert (big_o.degree, big_o.var, big_o.text) == (degree, var, text)
    assert big_o.span == sp(2, 19, 2, 19 + len(annotation))


def test_o_as_a_parameter_name():
    m = micro("f(O) O(O)")
    assert m.params[0].name == "O" and (m.big_o.degree, m.big_o.var) == (1, "O")


def test_unclosed_big_o():
    program, _, diags = parse_src("i use arch btw\nmicroservice f(n) O(n { }\n:wq\n")
    m = program.items[0]
    assert m.big_o.degree is None and m.big_o.text == "n"
    assert [d.message for d in diags] == [
        "Syntax error: expected `)`, found `{`.",
        "Syntax error: expected `)`, found `:wq`." + LISP,
    ]


# Expressions and precedence


@pytest.mark.parametrize(
    "src, tree",
    [
        ("1 + 2 * 3", "(1 + (2 * 3))"),
        ("1 - 2 - 3", "((1 - 2) - 3)"),
        ("8 / 2 % 3", "((8 / 2) % 3)"),
        ("(1 + 2) * 3", "((1 + 2) * 3)"),
        ("-x * 2", "((-x) * 2)"),
        ("- - x", "(-(-x))"),
        ("!a && b || c", "(((!a) && b) || c)"),
        ("a || b && c", "(a || (b && c))"),
        ("a == b && c != d", "((a == b) && (c != d))"),
        ("a < b == c >= d", "((a < b) == (c >= d))"),
        ("1 + 2 < 3 * 4", "((1 + 2) < (3 * 4))"),
        ("!(x < 1)", "(!(x < 1))"),
        ("f(1, g(2), -3)", "f(1, g(2), (-3))"),
        ("f()", "f()"),
        ("LGTM == 404", "(LGTM == 404)"),
        ('"text"', "'text'"),
    ],
)
def test_precedence(src, tree):
    assert sexp(expr(src)) == tree


def test_binary_span_includes_leading_paren():
    e = expr("(1 + 2) * 3")
    assert e.span == sp(3, 13, 3, 24)
    assert e.left.span == sp(3, 14, 3, 19)


def test_call_spans():
    e = expr("add(1, 2)")
    assert e.span == sp(3, 13, 3, 22)
    assert e.callee == ast.Ident("add", span=sp(3, 13, 3, 16))


def test_arguments_may_wrap_lines():
    assert sexp(expr("f(1,\n  2)")) == "f(1, 2)"


@pytest.mark.parametrize("src", ["1 < 2 < 3", "a == b == c", "1 <= 2 > 3", "a != b == c"])
def test_comparisons_are_non_associative(src):
    program, _, diags = parse_src(wrap(f"console.log {src}"))
    (d,) = diags
    assert d.code == "E400"
    assert d.message == "Chained comparisons aren't a thing here. This isn't Python."
    assert isinstance(program.items[0].body.stmts[0].value, ast.ErrorExpr)


# Pipes (Language Spec 9.4)

VOID = "`console.log` returns nothing. It's void, like my weekend plans."


@pytest.mark.parametrize(
    "src, tree",
    [
        ("a | f", "f(a)"),
        ("a | f | g(y)", "g(f(a), y)"),
        ("a | f() | g(1, 2)", "g(f(a), 1, 2)"),
        ("a + 1 | f", "f((a + 1))"),
        ("a || b | f", "f((a || b))"),
        ("-a | f", "f((-a))"),
        ("(a | f) + 1", "(f(a) + 1)"),
        ("f(a | g, 2)", "f(g(a), 2)"),
        ('"x" | f', "f('x')"),
    ],
)
def test_pipes_desugar_into_calls(src, tree):
    assert sexp(expr(src)) == tree


def test_pipe_stages_keep_their_own_spans():
    e = expr("3 | double | add(10)")
    assert e.span == sp(3, 26, 3, 33)
    assert e.callee.span == sp(3, 26, 3, 29)
    inner = e.args[0]
    assert inner.span == sp(3, 17, 3, 23)
    assert inner.callee == ast.Ident("double", span=sp(3, 17, 3, 23))
    assert inner.args[0].span == sp(3, 13, 3, 14)


def test_pipe_into_console_log_is_a_print():
    (stmt,) = stmts("3 | double | add(10) | console.log")
    assert isinstance(stmt, ast.Print)
    assert sexp(stmt.value) == "add(double(3), 10)"
    assert stmt.span == sp(3, 1, 3, 35)


def test_string_piped_into_console_log():
    (stmt,) = stmts('"piped" | console.log')
    assert isinstance(stmt, ast.Print)
    assert stmt.value == ast.StrLit("piped", span=sp(3, 1, 3, 8))


def test_pipe_without_console_log_is_an_expression_statement():
    (stmt,) = stmts("3 | f")
    assert isinstance(stmt, ast.ExprStmt)
    assert sexp(stmt.expr) == "f(3)"


def test_pipes_in_values_and_conditions():
    decl, cond = stmts("npm install v = 1 + 2 | double\nvibe check (x | f) == 1 { }")
    assert sexp(decl.value) == "double((1 + 2))"
    assert isinstance(cond, ast.If)


@pytest.mark.parametrize(
    "body, col",
    [
        ("npm install y = 5 | console.log", 21),
        ("console.log 5 | console.log", 17),
        ("ship it 5 | console.log", 13),
        ("git push --force y = 5 | console.log", 26),
        ("f(5 | console.log)", 7),
        ("5 | console.log | f", 5),
    ],
)
def test_pipe_into_console_log_used_as_a_value(body, col):
    assert errors(wrap(body)) == [(3, col, "E405", VOID)]


def test_void_pipe_value_is_an_error_expr():
    program, _, _ = parse_src(wrap("npm install y = 5 | console.log"))
    (decl,) = program.items[0].body.stmts
    assert decl.value == ast.ErrorExpr(span=sp(3, 17, 3, 32))


def test_only_a_pipe_can_follow_a_stage():
    assert errors(wrap("a | f + 1")) == [
        (3, 7, "E400", "Syntax error: expected end of line, found `+`.")
    ]


def test_pipe_stage_must_be_a_name():
    assert errors(wrap("a | 3")) == [
        (3, 5, "E400", "Syntax error: expected a name, found a magic number `3`.")
    ]


# Syntax errors and recovery


def test_missing_expression_keeps_the_declaration():
    src = (GOLDEN / "p0_e400_missing_expression.btw").read_text()
    program, _, diags = parse_src(src)
    decl, use = program.items[0].body.stmts
    assert decl.name.name == "x"
    assert decl.value == ast.ErrorExpr(span=sp(3, 20, 3, 20))
    assert isinstance(use, ast.Print)
    assert [d.message for d in diags] == [
        "Syntax error: expected an expression, found end of line."
    ]


def test_missing_equals_keeps_the_declaration():
    program, _, diags = parse_src(wrap("npm install x 5"))
    (decl,) = program.items[0].body.stmts
    assert isinstance(decl.value, ast.ErrorExpr)
    assert [x.message for x in diags] == ["Syntax error: expected `=`, found a magic number `5`."]


def test_recovery_continues_on_the_next_line():
    src = (GOLDEN / "p0_e400_recovery.btw").read_text()
    program, _, _ = parse_src(src)
    assert errors(src) == [(3, 22, "E400", "Syntax error: expected a name, found `=`.")]
    (use,) = program.items[0].body.stmts
    assert sexp(use.value) == "ghost"


def test_one_e400_per_statement():
    src = wrap("console.log ) ) +\nconsole.log 1 2 3\nnpm install = = =")
    assert [e[2:] for e in errors(src)] == [
        ("E400", "Syntax error: expected an expression, found `)`."),
        ("E400", "Syntax error: expected end of line, found a magic number `2`."),
        ("E400", "Syntax error: expected a name, found `=`."),
    ]


def test_error_inside_block_does_not_spend_the_outer_statement():
    src = wrap("vibe check LGTM {\n    console.log +\n}\nconsole.log 1 1")
    assert [(line, msg) for line, _, _, msg in errors(src)] == [
        (4, "Syntax error: expected an expression, found `+`."),
        (6, "Syntax error: expected end of line, found a magic number `1`."),
    ]


def test_found_wording():
    cases = {
        "console.log foo bar": "found `bar`, whoever that is",
        "console.log 1 42": "found a magic number `42`",
        'console.log 1 "s"': "found a hardcoded string",
        "console.log 1 LGTM": "found `LGTM`",
        "console.log 1 404": "found `404`",
        "console.log 1 skill   issue": "found `skill issue`",
        "console.log": "found end of line",
    }
    for body, wording in cases.items():
        ((_, _, _, message),) = errors(wrap(body))
        assert wording in message, (body, message)


def test_reserved_word_as_name():
    for word in ["sudo", "serve", "doomscroll", "microservice", "LGTM"]:
        src = wrap(f"npm install {word} = 1")
        assert errors(src) == [
            (3, 13, "E400", f"Syntax error: expected a name, found `{word}`.")
        ], word


def test_sudo_misuse():
    src = wrap("sudo console.log 1")
    msg = "`sudo` only works with `git push --force` and `git revert`."
    assert errors(src) == [(3, 6, "E400", msg)]
    program, _, _ = parse_src(src)
    assert isinstance(program.items[0].body.stmts[0], ast.Print)


def test_unexpected_character_is_left_to_the_lexer():
    src = (GOLDEN / "p0_e400_unexpected_char.btw").read_text()
    program, lex_diags, diags = parse_src(src)
    assert [d.message for d in lex_diags] == ["Unexpected character `@`."]
    assert diags == []
    assert isinstance(program.items[0].body.stmts[0], ast.Print)


def test_git_push_without_force_is_left_to_the_lexer():
    program, lex_diags, diags = parse_src(wrap("git push x = 2\ngit push = 2"))
    assert len(lex_diags) == 2 and diags == []
    (assign,) = program.items[0].body.stmts
    assert isinstance(assign, ast.Assign) and assign.name.name == "x"


def test_unterminated_string_still_parses():
    program, lex_diags, diags = parse_src(wrap('console.log "never finished'))
    assert diags == [] and len(lex_diags) == 1
    assert program.items[0].body.stmts[0].value.value == "never finished"


def test_missing_brace_at_end_of_file_closes_every_block():
    src = "i use arch btw\nserve localhost:3000 {\n doomscroll LGTM {\n  vibe check LGTM {\n"
    program, _, diags = parse_src(src)
    assert errors(src) == [
        (5, 1, "E400", "Syntax error: expected `}`, found end of file."),
        (4, 19, "E408", "Error: program never exited. Classic Vim user."),
    ]
    loop = program.items[0].body.stmts[0]
    assert isinstance(loop.body.stmts[0], ast.If)


def test_missing_brace_before_next_item():
    src = "i use arch btw\nmicroservice f() {\n ship it 1\nserve localhost:3000 { }\n:wq\n"
    program, _, _ = parse_src(src)
    assert [type(i).__name__ for i in program.items] == ["Microservice", "Serve"]
    assert errors(src) == [(4, 1, "E400", "Syntax error: expected `}`, found `serve`.")]


def test_brace_on_the_next_line_still_parses_the_block():
    src = wrap("vibe check LGTM\n{\n console.log 1\n}\nconsole.log 2")
    program, _, _ = parse_src(src)
    assert errors(src) == [(3, 16, "E400", "Syntax error: expected `{`, found end of line.")]
    if_, after = program.items[0].body.stmts
    assert len(if_.then.stmts) == 1 and isinstance(after, ast.Print)


def test_junk_before_brace_is_skipped():
    src = wrap("doomscroll x < ) junk {\n console.log 1\n}")
    program, _, _ = parse_src(src)
    assert [e[3] for e in errors(src)] == ["Syntax error: expected an expression, found `)`."]
    (loop,) = program.items[0].body.stmts
    assert len(loop.body.stmts) == 1


def test_stray_block_keeps_braces_balanced():
    src = wrap("{ console.log 1 }\nconsole.log 2")
    program, _, _ = parse_src(src)
    assert [e[3] for e in errors(src)] == ["Syntax error: expected a statement, found `{`."]
    assert [type(s).__name__ for s in program.items[0].body.stmts] == ["Print"]


def test_dangling_skill_issue():
    src = wrap("skill issue { }")
    assert [e[3] for e in errors(src)] == [
        "Syntax error: expected a statement, found `skill issue`."
    ]


def test_unclosed_paren_is_reported_again_at_wq():
    src = wrap("console.log (1 + 2")
    assert errors(src) == [
        (4, 1, "E400", "Syntax error: expected `)`, found `}`."),
        (5, 1, "E400", "Syntax error: expected `)`, found `:wq`." + LISP),
    ]


def test_unclosed_paren_at_end_of_file_replaces_missing_brace():
    src = "i use arch btw\nserve localhost:3000 {\n  vibe check (x {\n    console.log 1\n"
    assert errors(src) == [
        (3, 17, "E400", "Syntax error: expected `)`, found `{`."),
        (5, 1, "E400", "Syntax error: expected `)`, found end of file." + LISP),
        (4, 17, "E408", "Error: program never exited. Classic Vim user."),
    ]


def test_unclosed_paren_ignores_extra_closing_parens():
    # `)` with nothing open doesn't count, just as in the lexer: the `(` stays open.
    src = wrap("console.log 1 ) (")
    assert [e[3] for e in errors(src)] == [
        "Syntax error: expected end of line, found `)`.",
        "Syntax error: expected `)`, found `:wq`." + LISP,
    ]


def test_closed_parens_are_not_reported():
    assert errors(wrap("console.log f((1), (2 + (3)))")) == []


def test_unclosed_paren_after_wq_is_only_trailing():
    program, _, diags = parse_src(wrap("") + "(\n")
    assert diags == [] and program.trailing_span is not None


def test_bad_params_recover_to_the_body():
    src = "i use arch btw\nmicroservice f(a b) O(1) {\n ship it a\n}\n:wq\n"
    program, _, _ = parse_src(src)
    assert errors(src) == [
        (2, 18, "E400", "Syntax error: expected `)`, found `b`, whoever that is.")
    ]
    m = program.items[0]
    assert [p.name for p in m.params] == ["a"] and m.big_o.degree == 0
    assert len(m.body.stmts) == 1


def test_serve_without_port():
    src = "i use arch btw\nserve { }\n:wq\n"
    program, _, _ = parse_src(src)
    assert errors(src) == [
        (2, 7, "E400", "Syntax error: expected `localhost:3000`, found `{`.")
    ]
    assert isinstance(program.items[0], ast.Serve)


def test_other_port_is_accepted():
    program, _, diags = parse_src("i use arch btw\nserve localhost:5000 { }\n:wq\n")
    assert diags == [] and program.items[0].port == 5000


def test_port_8080_is_roasted():
    program, _, diags = parse_src("i use arch btw\nserve localhost:8080 { }\n:wq\n")
    (d,) = diags
    assert (d.code, d.severity, d.span) == ("E409", Severity.ERROR, sp(2, 7, 2, 21))
    assert d.message == (
        "Error: port 8080 is already in use by a Spring Boot app you forgot about. Use 3000."
    )
    assert program.items[0].port == 8080


@pytest.mark.parametrize(
    "body, message",
    [
        ("console.log 1 === 1", "This isn't JavaScript. Use `==`."),
        ("console.log x;", "Semicolons are deprecated. This is a modern language."),
        ("i++", "We don't do that here. Use `git push --force i = i + 1`."),
        ("npm install x = 007", "Leading zeros? This isn't octal, James Bond."),
    ],
)
def test_roasts_are_the_only_e400(body, message):
    _, lex_diags, diags = parse_src(wrap(body))
    assert [(d.code, d.message) for d in lex_diags] == [("E400", message)]
    assert diags == []


# Top level


def test_top_level_statement():
    src = (GOLDEN / "p0_e400_top_level_statement.btw").read_text()
    assert errors(src) == [
        (
            2,
            1,
            "E400",
            "Syntax error: `console.log` outside a `microservice` or `serve`. "
            "Serverless still needs a server.",
        )
    ]
    program, _, _ = parse_src(src)
    assert len(program.items) == 1


@pytest.mark.parametrize(
    "src, shown",
    [
        ("git   push   --force x = 1", "git push --force"),
        ("sudo git push --force X = 1", "sudo"),
        ("vibe\tcheck LGTM { }", "vibe check"),
        ("doomscroll LGTM { }", "doomscroll"),
        ("touch grass", "touch grass"),
        ("ship it", "ship it"),
        ("git revert x", "git revert"),
        ("git log x", "git log"),
    ],
)
def test_top_level_statement_keywords(src, shown):
    full = f"i use arch btw\n{src}\nserve localhost:3000 {{ }}\n:wq\n"
    ((_, _, _, message),) = errors(full)
    assert message.startswith(f"Syntax error: `{shown}` outside a `microservice` or `serve`.")


def test_top_level_generic_error_skips_to_next_item_line():
    src = "i use arch btw\nx = 1 {\n console.log 2\n}\nserve localhost:3000 { }\n:wq\n"
    program, _, _ = parse_src(src)
    assert errors(src) == [
        (
            2,
            1,
            "E400",
            "Syntax error: expected `microservice`, `serve` or `npm install`, "
            "found `x`, whoever that is.",
        )
    ]
    assert [type(i).__name__ for i in program.items] == ["Serve"]


def test_top_level_git_push_is_left_to_the_lexer():
    src = "i use arch btw\ngit push x = 1\nserve localhost:3000 { }\n:wq\n"
    program, lex_diags, diags = parse_src(src)
    assert diags == [] and len(lex_diags) == 1


# Robustness


@pytest.mark.parametrize(
    "src",
    [
        "",
        "{",
        "}",
        "(((",
        ")))",
        ":wq :wq :wq",
        "microservice",
        "microservice f(",
        "microservice f(a,",
        "microservice f() O(",
        "serve",
        "serve localhost:3000",
        "npm install",
        "npm install x",
        "vibe check",
        "i use arch btw\nserve localhost:3000 { vibe check",
        "i use arch btw\nserve localhost:3000 { vibe check LGTM { } skill issue",
        "i use arch btw\nserve localhost:3000 { sudo",
        "i use arch btw\nserve localhost:3000 { sudo sudo sudo",
        "i use arch btw\nserve localhost:3000 { f(1, 2",
        "i use arch btw\nserve localhost:3000 { console.log -",
        "i use arch btw\nserve localhost:3000 { } } } {",
        "@ # $",
        "\n\n\n",
    ],
)
def test_never_raises(src):
    program, _, diags = parse_src(src)
    assert isinstance(program, ast.Program)
    assert all(d.code != "E500" for d in diags)
    format_ast(program)


def test_deep_nesting_is_an_internal_error_not_a_crash():
    program, _, diags = parse_src(wrap("console.log " + "(" * 5000 + "1" + ")" * 5000))
    assert isinstance(program, ast.Program)
    assert [d.code for d in diags] == ["E500"]


def test_tokens_without_eof():
    program, diags = parse([Token(K.ARCH, "i use arch btw", sp(1, 1, 1, 15))])
    assert program.has_arch and [d.code for d in diags] == ["E408"]


# Foreign keywords (Language Spec 13)


@pytest.mark.parametrize(
    "body",
    [
        "npm install if = 1\nconsole.log if",
        "npm install print = 1\ngit push --force print = print + 1",
        "print(5)",
        "return - 1",
        "if (x)",
        "while (a) || b",
        "for (a) + 1",
        "console.log true",
    ],
)
def test_foreign_words_are_still_identifiers(body):
    stmts(body)  # no parser diagnostics


@pytest.mark.parametrize(
    "body, roast",
    [
        ("if x > 1 { }", "`if` is a boomer conditional. Use `vibe check`."),
        ("if (x > 1) { }", "`if` is a boomer conditional. Use `vibe check`."),
        ("if ((a) || (b)) {\n}", "`if` is a boomer conditional. Use `vibe check`."),
        ("if !x { }", "`if` is a boomer conditional. Use `vibe check`."),
        ("else { }", "`else`? That's a `skill issue`. Literally, type `skill issue`."),
        ("else if x { }", "`else`? That's a `skill issue`. Literally, type `skill issue`."),
        ("while LGTM { }", "Nobody uses `while` anymore. Use `doomscroll`, like it's 2am."),
        ("for (i) { }", "Nobody uses `for` anymore. Use `doomscroll`, like it's 2am."),
        ("break touch grass", "Don't `break`. Go `touch grass`."),
        ("return 0", "No returns, only deploys. Use `ship it`."),
        ("return 404", "No returns, only deploys. Use `ship it`."),
        ("let x = 1", "`let`? Real variables come from `npm install`."),
        ("const X = 1", "`const` is just a global install. Use `npm install -g`."),
        ("fn f() { }", "`fn` is a monolith mindset. Use `microservice`."),
        ('printf "%d"', "`printf`? Real developers debug with `console.log`."),
    ],
)
def test_foreign_statement_roast(body, roast):
    assert errors(wrap(body)) == [(3, 1, "E400", roast)]


@pytest.mark.parametrize("word", ["function", "def", "const", "let", "if", "print"])
def test_foreign_item_roast(word):
    """At top level any foreign word is roasted, whatever follows it."""
    src = f"i use arch btw\n{word} f(n) {{\n    ship it n\n}}\nserve localhost:3000 {{\n}}\n:wq\n"
    [(line, col, code, message)] = errors(src)
    assert (line, col, code) == (2, 1, "E400")
    assert message.startswith(f"`{word}`")


def test_foreign_roast_fix_swaps_the_word():
    _, _, [diag] = parse_src(wrap("    if (x) {\n    }"))
    assert diag.fixes == [Fix("Use vibe check", [Edit(sp(3, 5, 3, 7), "vibe check")])]


def test_foreign_roast_drops_the_statement():
    program, _, _ = parse_src(wrap("return x\nconsole.log 1"))
    [stmt] = program.items[0].body.stmts
    assert isinstance(stmt, ast.Print)


# Debug dump


def test_format_ast():
    program, _, _ = parse_src("i use arch btw\nserve localhost:3000 {\n    ship it -x\n}\n:wq\n")
    assert format_ast(program) == (
        "Program 1:1-6:1 has_arch=True wq_span=5:1-5:4 trailing_span=None\n"
        "  items[0]: Serve 2:1-4:2 port=3000\n"
        "    body: Block 2:22-4:2\n"
        "      stmts[0]: Return 3:5-3:15\n"
        "        value: Unary 3:13-3:15 op='-'\n"
        "          operand: Var 3:14-3:15 name='x'\n"
    )


# The golden corpus


def golden_programs():
    return [pytest.param(p, id=p.stem) for p in sorted(GOLDEN.glob("*.btw"))]


@pytest.mark.parametrize("program", golden_programs())
def test_golden_syntax_errors(program):
    """Every golden program parses, with exactly the E400, E408 and W208 its .diag lists."""
    _, lex_diags, diags = parse_src(program.read_text())
    seen = set()
    got = []
    for d in [*lex_diags, *diags]:  # the driver keeps the first of exact duplicates
        if d.code in ("E400", "E408", "E500", "W208") and (d.code, d.span) not in seen:
            seen.add((d.code, d.span))
            pos = f"{d.span.start.line + 1}:{d.span.start.col + 1}"
            got.append(f"{pos}: {d.severity.value}[{d.code}]: {d.message}")
    sidecar = program.with_suffix(".diag")
    lines = sidecar.read_text().splitlines() if sidecar.exists() else []
    want = [line for line in lines if any(f"[{c}]" in line for c in ("E400", "E408", "W208"))]
    assert sorted(got) == sorted(want)
