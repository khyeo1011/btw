# Releasing btw

Releases are cut from `main` by pushing a `vX.Y.Z` tag. The
[Release workflow](.github/workflows/release.yml) then checks the tag against
`pyproject.toml` and `CHANGELOG.md`, runs the tests, builds the wheel and
sdist, smoke-tests the installed wheel with `scripts/check-dist.sh` and
creates a GitHub release with both files attached.

## What a release contains

- `btw-X.Y.Z-py3-none-any.whl`: the `btw` and `btw-lsp` commands. It carries
  `runtime/btw_rt.c` as `btw/btw_rt.c` (through the `src/btw/btw_rt.c`
  symlink), so `btw build` works without a checkout. Native builds still need
  gcc and GNU as on Linux x86-64.
- `btw-X.Y.Z.tar.gz`: the sdist, with the runtime, the specs and the full test
  suite, so `uv run pytest` works from the unpacked archive.

## Checklist

1. On a `release/X.Y.Z` branch, set the version (`uv version X.Y.Z`; it also
   updates `uv.lock`).
2. In `CHANGELOG.md`, rename `[Unreleased]` entries into a new
   `## [X.Y.Z] - YYYY-MM-DD` section and update the compare links at the end.
3. Check the package locally:

   ```
   uv run pytest
   rm -rf dist && uv build --no-sources
   scripts/check-dist.sh dist
   ```

4. Open a pull request into `main` and merge it once CI is green (the
   `package` job runs the same distribution check).
5. Tag the merge commit and push the tag:

   ```
   git switch main && git pull
   git tag -a vX.Y.Z -m "btw X.Y.Z"
   git push origin vX.Y.Z
   ```

6. Watch the Release workflow. If it fails before the release is created,
   fix it on `main`, delete the tag (`git push origin :vX.Y.Z`) and tag again.

## Publishing to PyPI (optional)

The workflow's last step publishes with `uv publish` through
[trusted publishing](https://docs.pypi.org/trusted-publishers/) and is off by
default. To turn it on:

1. Pick a project name that is free on PyPI (`btw` itself may be taken) and
   set it as `name` in `pyproject.toml`; the commands stay `btw` and
   `btw-lsp`.
2. On PyPI, add a trusted publisher for repository `khyeo1011/btw`, workflow
   `release.yml`, with no environment.
3. In the repository settings, set the Actions variable `PUBLISH_TO_PYPI` to
   `true`.

## The VS Code extension

`editors/vscode` is not part of the Python package. To ship it, install
`@vscode/vsce` and run `npx vsce package` in that directory, then attach the
`.vsix` to the GitHub release. It still needs `btw-lsp` on `PATH`.
