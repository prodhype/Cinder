# large_project — Breakout with SDL2 + SDL_mixer

A multi-module Cinder project that opens an SDL2 window, draws a tiny Breakout-style
game, and plays WAV sound effects through SDL_mixer.

## Layout

```text
cinder.toml
assets/                 # hit.wav, brick.wav, wall.wav, lose.wav
src/
  main.ci
  sdl/                  # bindings, app, events, draw, audio
  game/                 # config, math2d, paddle, ball, bricks, world, loop
```

Thirteen `.ci` modules under `src/`. `sdl/bindings.ci` declares opaque C types
(`type SDL_Window`, and so on) so other modules can use `*sdl.SDL_Renderer`
directly without `*void` handle wrappers.

The manifest already lists the short library names:

```toml
[native]
libraries = ["SDL2", "SDL2_mixer"]
```

## Controls

- Left / Right or A / D — move paddle
- Space — launch ball (or restart after win/lose)
- Esc or close window — quit

Score and lives also print to stdout. The on-screen HUD is colored rect bars
(no font dependency).

## Dependencies

Install SDL2 and SDL_mixer system-wide (dynamic link, fine for local play):

```sh
# macOS (Homebrew)
brew install sdl2 sdl2_mixer

# Debian/Ubuntu
sudo apt install libsdl2-dev libsdl2-mixer-dev
```

## Build and run

Run commands from this directory so `assets/*.wav` resolve.

**macOS (Homebrew)** — libraries come from `cinder.toml`; pass include/search paths:

```sh
cinder build . -o breakout \
  -I "$(brew --prefix)/include" \
  -I "$(brew --prefix)/include/SDL2" \
  --ldflag="-L$(brew --prefix)/lib"

./breakout
```

Or:

```sh
cinder run . \
  -I "$(brew --prefix)/include" \
  -I "$(brew --prefix)/include/SDL2" \
  --ldflag="-L$(brew --prefix)/lib"
```

**Linux:**

```sh
cinder build . -o breakout \
  -I /usr/include \
  -I /usr/include/SDL2

./breakout
```

Both `-I …/include` and `-I …/include/SDL2` are typically needed: Cinder emits
`#include "SDL2/SDL.h"`, while SDL_mixer headers include `"SDL_stdinc.h"` as a
sibling of `SDL.h`. CLI `-I` / `--ldflag` append after manifest `[native]` values.

## Single-binary / vendored static libs

For a redistributable executable, vendor headers and static archives under the
project (for example `third_party/sdl2/`) and point the manifest at them with
**project-relative** paths—no machine-local Homebrew prefixes:

```toml
[native]
include-dirs = [
  "third_party/sdl2/include",
  "third_party/sdl2/include/SDL2",
]
library-dirs = ["third_party/sdl2/lib"]
libraries = ["SDL2", "SDL2_mixer"]
# Prefer explicit archives when you want the linker to pull static objects:
link-files = [
  "third_party/sdl2/lib/libSDL2.a",
  "third_party/sdl2/lib/libSDL2_mixer.a",
]
# Escape hatch for platform flags, e.g. macOS frameworks or -Wl options:
# ldflags = ["-framework", "Cocoa"]
```

Then `cinder build . -o breakout` needs no extra `-I`/`-L`/`-l` on the CLI. The
resulting binary still embeds the Cinder runtime; static SDL archives keep
third-party code inside that one file (subject to each library’s license).

## Notes

- Manual demo only — not exercised by CI (needs SDL2, SDL_mixer, and a display).
- Type-check without linking: `cinder check .`
- Generated build cache lives under `.cinder/` (gitignored).
