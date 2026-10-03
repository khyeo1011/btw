from btw.diagnostics import Diagnostic, Position, Severity, Span, line_span, sort_diagnostics


def at(code, line, column):
    return Diagnostic(code, Severity.ERROR, code, Span(Position(line, column), Position(line, column + 1)))


def test_sorted_by_line_column_then_code():
    unsorted = [at("E418", 3, 0), at("E404", 1, 5), at("E409", 1, 2), at("E400", 1, 2)]
    assert [d.code for d in sort_diagnostics(unsorted)] == ["E400", "E409", "E404", "E418"]


def test_exact_duplicates_dropped():
    assert sort_diagnostics([at("E404", 1, 5), at("E404", 1, 5), at("E405", 1, 5)]) == [
        at("E404", 1, 5),
        at("E405", 1, 5),
    ]


def test_line_span_covers_the_line_without_its_ending():
    assert line_span("i use arch btw\r\n:wq\n", 0) == Span(Position(0, 0), Position(0, 14))


def test_line_span_counts_utf16_units():
    assert line_span('"🚀"\n', 0) == Span(Position(0, 0), Position(0, 4))
