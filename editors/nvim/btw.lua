vim.filetype.add({ extension = { btw = "btw" } })

vim.lsp.config("btw", {
  cmd = { "btw-lsp" },
  filetypes = { "btw" },
  root_markers = { ".git" },
})
vim.lsp.enable("btw")

vim.diagnostic.config({ virtual_text = true })
