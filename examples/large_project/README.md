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

Thirteen `.ci` modules under `src/`. Opaque SDL handles are wrapped in Cinder
structs in `sdl/bindings.ci` so other modules can pass them safely.

## Controls

- Left / Right or A / D — move paddle
- Space — launch ball (or restart after win/lose)
- Esc or close window — quit

Score and lives also print to stdout. The on-screen HUD is colored rect bars
(no font dependency).

## Dependencies

Install SDL2 and SDL_mixer system-wide:

```sh
# macOS (Homebrew)
brew install sdl2 sdl2_mixer

# Debian/Ubuntu
sudo apt install libsdl2-dev libsdl2-mixer-dev
```

## Build and run

Run commands from this directory so `assets/*.wav` resolve.

**macOS (Homebrew):**

```sh
cinder build . -o breakout \
  -I "$(brew --prefix)/include" \
  -I "$(brew --prefix)/include/SDL2" \
  --ldflag="-L$(brew --prefix)/lib" \
  --ldflag=-lSDL2 \
  --ldflag=-lSDL2_mixer

./breakout
```

Or with `cinder run` (same include/link flags):

```sh
cinder run . \
  -I "$(brew --prefix)/include" \
  -I "$(brew --prefix)/include/SDL2" \
  --ldflag="-L$(brew --prefix)/lib" \
  --ldflag=-lSDL2 \
  --ldflag=-lSDL2_mixer
```

**Linux (pkg-config):**

```sh
cinder build . -o breakout \
  -I /usr/include \
  -I /usr/include/SDL2 \
  --ldflag=-lSDL2 \
  --ldflag=-lSDL2_mixer

./breakout
```

`cinder.toml` does not store linker flags yet; pass `-I` / `--ldflag` on the CLI.
Both `-I …/include` and `-I …/include/SDL2` are needed: Cinder emits
`#include "SDL2/SDL.h"`, while SDL_mixer headers include `"SDL_stdinc.h"` as a
sibling of `SDL.h`.

## Notes

- Manual demo only — not exercised by CI (needs SDL2, SDL_mixer, and a display).
- Type-check without linking: `cinder check .`
- Generated build cache lives under `.cinder/` (gitignored).
