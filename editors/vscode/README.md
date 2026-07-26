# Cinder Language Support

This extension adds Cinder language support to Cursor and VS Code:

- `.ci` file detection
- TextMate syntax highlighting for declarations, keywords, types, literals, comments,
  decorators, and operators
- bracket pairing, comment toggling, folding, and colon-based indentation

The compiler lexer in `../../cinder/lexer.py` is the source of truth for the grammar.

## Install in Cursor

From the repository root, package the extension:

```sh
cd editors/vscode
npx --yes @vscode/vsce package --out cinder-language-support.vsix
```

### macOS

The `cursor` command may point to the Cursor Agent CLI instead of the desktop IDE.
Install the extension with the desktop app's bundled launcher:

```sh
"/Applications/Cursor.app/Contents/Resources/app/bin/cursor" \
  --install-extension "$PWD/cinder-language-support.vsix"
```

Alternatively, open the Command Palette in Cursor, run
**Extensions: Install from VSIX...**, and select `cinder-language-support.vsix`.

Reload Cursor after installation. The extension automatically selects Cinder mode for
files ending in `.ci`.

The generated `.vsix` is a local build artifact and should not be committed.

## Develop

Open this directory in Cursor or VS Code and start debugging to launch an Extension
Development Host. There is no build step; changes to the JSON grammar take effect after
reloading the development host.

From the repository root, run the syntax scope tests with:

```sh
npx --yes vscode-tmgrammar-test \
  -g editors/vscode/syntaxes/cinder.tmLanguage.json \
  "editors/vscode/tests/*.ci"
```
