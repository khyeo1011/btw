"use strict";

const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

let client;

function activate(context) {
  const command = vscode.workspace.getConfiguration("btw").get("serverPath", "btw-lsp");
  const outputChannel = vscode.window.createOutputChannel("btw");

  const serverOptions = {
    run: { command, transport: TransportKind.stdio },
    debug: { command, transport: TransportKind.stdio },
  };
  const clientOptions = {
    documentSelector: [{ scheme: "file", language: "btw" }],
    outputChannel,
  };

  client = new LanguageClient("btw", "btw", serverOptions, clientOptions);
  context.subscriptions.push(outputChannel);
  return client.start();
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
