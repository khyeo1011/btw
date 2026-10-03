def pytest_addoption(parser):
    parser.addoption(
        "--tier",
        type=int,
        default=None,
        help="only run golden tests of tier N and below (p0_ is tier 0)",
    )
    parser.addoption(
        "--bless",
        action="store_true",
        help="overwrite golden expectations with actual output (humans only)",
    )
