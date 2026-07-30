# large_project — Breakout with SDL2 + SDL_mixer

A multi-module Cinder project that opens an SDL2 window, draws a tiny Breakout-style
game, and plays WAV sound effects through SDL_mixer.

## Layout

```text
cinder.toml
assets/                 # hit.wav, brick.wav, wall.wav, lose.wav
scripts/vendor_static_sdl.sh
third_party/sdl2/       # static headers + .a (generated; see below)
src/
  main.ci
  sdl/                  # bindings, app, events, draw, audio
  game/                 # config, math2d, paddle, ball, bricks, world, loop
```

Thirteen `.ci` modules under `src/`. `sdl/bindings.ci` declares opaque C types
(`type SDL_Window`, and so on) so other modules can use `*sdl.SDL_Renderer`
directly without `*void` handle wrappers.

## Controls

- Left / Right or A / D — move paddle
- Space — launch ball (or restart after win/lose)
- Esc or close window — quit

Score and lives also print to stdout. The on-screen HUD is colored rect bars
(no font dependency).

## Single-binary build (default)

`cinder.toml` links vendored static archives under `third_party/sdl2/`. Populate
them once (needs `cmake`, `curl`, a C toolchain):

```sh
./scripts/vendor_static_sdl.sh
```

That builds classic SDL2 2.30.x and a WAV-only SDL2_mixer into
`third_party/sdl2/{include,lib}`. Then:

```sh
cinder build . -o breakout
./breakout
```

No Homebrew SDL install is required for this path. The executable embeds Cinder’s
runtime plus SDL2 / SDL_mixer (system frameworks such as Cocoa remain dynamic).
WAV assets under `assets/` are still loaded from disk at runtime.

## Dynamic link (optional)

To use system SDL instead, switch `[native]` to short library names and pass
include/search paths on the CLI:

```toml
[native]
libraries = ["SDL2", "SDL2_mixer"]
```

```sh
# macOS (Homebrew)
brew install sdl2 sdl2_mixer
cinder build . -o breakout \
  -I "$(brew --prefix)/include" \
  -I "$(brew --prefix)/include/SDL2" \
  --ldflag="-L$(brew --prefix)/lib"

# Linux
sudo apt install libsdl2-dev libsdl2-mixer-dev
cinder build . -o breakout \
  -I /usr/include \
  -I /usr/include/SDL2
```

Both `-I …/include` and `-I …/include/SDL2` are typically needed: Cinder emits
`#include "SDL2/SDL.h"`, while SDL_mixer headers include `"SDL_stdinc.h"` as a
sibling of `SDL.h`.

## Notes

- Manual demo only — not exercised by CI (needs a display for the interactive run).
- Type-check without linking: `cinder check .`
- Generated build cache lives under `.cinder/` (gitignored).
- Vendor build trees/tarballs live under `.vendor/` (gitignored).
