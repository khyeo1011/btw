# btw for Neovim

Needs Neovim 0.11 or newer (`vim.lsp.config` and `vim.lsp.enable`).

- `btw.lua`: maps `*.btw` to the `btw` filetype and starts `btw-lsp` over
  stdio for it, with diagnostics shown as virtual text.
- `syntax/btw.vim`: keyword highlighting, which works without the server.

## Load both

Permanently, in your `init.lua` (use the absolute path to this directory):

```lua
vim.opt.rtp:append("/path/to/btw/editors/nvim") -- lets Neovim find syntax/btw.vim
dofile("/path/to/btw/editors/nvim/btw.lua")     -- filetype and language server
```

For one session, from the repo root:

```
uv run nvim --cmd "set rtp+=editors/nvim" --cmd "luafile editors/nvim/btw.lua" tests/golden/p0_fizzbuzz.btw
```

Use `--cmd`, not `-c`: `-c` runs after the file is opened, too late for the
filetype to be detected. `uv run` puts the project's `btw-lsp` on `PATH`;
without it, `btw-lsp` must be on `PATH` some other way (for example
`uv tool install -e .`).

## Debugging

- `:set filetype? syntax?` should both say `btw`.
- `:checkhealth vim.lsp` shows attached clients and the log path.
- `:lua =vim.lsp.get_clients()` lists running clients.
- The server's stderr goes to the LSP log (`:lua =vim.lsp.log.get_filename()`).
