# Effect recipes

An effect is data. Adding one is a row in a database, not a firmware build.

This page is the format. It is a contract between `api/` and
`firmware/led_controller/`, which is why they live in one repository — a change
here has to land on both sides in one commit, and the failure mode otherwise is
a strip that goes dark and does not say why.

---

## Why there are only two slots

Twelve compiled effects existed before this, and they were not twelve different
things. Every one answers the same two questions, once per LED, per frame:

1. **What colour is this LED?** — pick a point in a palette
2. **How bright is it?** — a number from 0 to 1

Aurora and Ocean turned out to be the *same effect*. Both drift a colour band
along the strip while a slow sine, phased per LED, moves the brightness. The
only differences were the palette and four numbers:

```c
// aurora
hue        = effectHue + i*2, narrowed to greens and blues
brightness = beatsin8(3 + (i%4), 50, 255, 0, i*5)

// ocean
colour     = a fixed blue/cyan ramp
brightness = beatsin8(6 + (i%5), 100, 255, 0, i*10)
```

Chase and Cylon are one bright blob with different motion. Sparkle and Confetti
are one impulse-and-decay with different colour sources. So the engine is one
line:

```
colour = palette(sample(p, t)) * level(p, t)
```

`sample` says where in the palette to read. `level` says how bright. Everything
else is parameters.

## Position is normalised

`p = i / (n - 1)`. Zero is the start of the strip, one is the end, whatever the
length.

This is the only place the LED count is used, and it is the point of the whole
exercise: an effect authored once looks the same on a 30-LED desk strip and a
173-LED wall strip. Written against raw indices instead, a chase tuned on one
crawls on the other.

---

## The format

```json
{
  "effect": "ocean",
  "recipe": {
    "palette": [[0, 0, 64], [0, 128, 255], [255, 255, 255]],
    "sample":  { "mode": "scroll", "speed": 0.3, "span": 1.0 },
    "level":   { "mode": "solid" },
    "frame_ms": 20
  }
}
```

Sent to `lights/<device_id>/set` over MQTT. The device stores it in NVS as the
raw JSON it arrived as — not as unpacked fields — so the format can grow, and a
strip that reboots at 3am comes back as itself without waiting for the server.

| Field | Meaning |
|---|---|
| `palette` | 1–8 stops, each `[r, g, b]` or the string `"device"`. Interpolated, and **circular** — the last stop wraps back to the first so a scroll has no seam |
| `sample` | Where in the palette each LED reads |
| `level` | How bright each LED is, 0–1 |
| `frame_ms` | Frame interval, 5–500, default 20 |

### `sample` modes

| Mode | Parameters | What it does |
|---|---|---|
| `fixed` | `at`, `speed` | One palette point for the whole strip. With `speed`, the whole strip cycles together |
| `position` | `span` | A static gradient along the strip |
| `scroll` | `span`, `speed` | A gradient that moves. `span` 2 fits two palette cycles on the strip |
| `noise` | `scale`, `speed` | A smooth noise field read along the strip, drifting in time. This is LIFX's Morph, and most of its ambient themes |
| `random` | — | Per-LED random, re-rolled when a pixel is struck. Only useful with `level: impulse` — this is Confetti |

### `level` modes

| Mode | Parameters | What it does |
|---|---|---|
| `solid` | `max` | Constant |
| `wave` | `min`, `max`, `speed`, `phase`, `detune` | A sine. `phase` offsets it along the strip; `detune` varies the *period* per LED |
| `blob` | `min`, `max`, `speed`, `width`, `trail`, `pingpong` | A bright region that moves. `pingpong` true is Cylon, false is Chase |
| `impulse` | `min`, `max`, `rate`, `decay` | Random pixels struck and faded. Sparkle, Confetti |
| `square` | `min`, `max`, `speed` | On/off. Strobe |
| `flicker` | `min`, `max` | Per-LED random each frame. Candle |

### The `"device"` stop

A palette stop written as the string `"device"` resolves, on the strip, to
whatever colour that strip is currently set to.

```json
{ "palette": ["device"], "sample": {"mode": "fixed"},
  "level": {"mode": "blob", "speed": 0.4, "width": 0.02, "pingpong": true} }
```

This exists because moving an effect into data cost it a feature. Chase, cylon,
sparkle, breathing and strobe all used to render in the colour you had picked,
and a recipe carries its own fixed palette — so the first translation of them
silently stopped following the colour picker.

It is resolved at render time rather than when the recipe is parsed, so changing
the colour takes effect immediately without re-sending anything. And it
composes: `["device", [0,0,0]]` is a gradient from your colour down to black.

### `detune` is not optional decoration

With every LED on the same period, the strip breathes in unison and reads as
cheap. The original aurora varied the sine **period** per LED, not just the
phase:

```c
beatsin8(3 + (i % 4), 50, 255, 0, i * 5)
        // ^^^^^^^^^ this
```

That small dissonance is the entire difference between a shimmer and a pulse. It
is the parameter most likely to be left out and the hardest to diagnose
afterwards, because the effect still "works" — it just looks wrong in a way
nobody can name.

---

## Worked examples

**Aurora** — verified on the desk strip.

```json
{
  "palette": [[0,255,60], [0,200,180], [0,120,255], [40,220,140]],
  "sample":  { "mode": "scroll", "speed": 0.05, "span": 2 },
  "level":   { "mode": "wave", "min": 0.2, "max": 1.0,
               "speed": 0.35, "phase": 1.5, "detune": 1.0 },
  "frame_ms": 30
}
```

**Ocean** — the same recipe. Only the palette and the numbers change.

```json
{
  "palette": [[0,40,90], [0,120,200], [80,220,255]],
  "sample":  { "mode": "position", "span": 1 },
  "level":   { "mode": "wave", "min": 0.4, "max": 1.0,
               "speed": 0.5, "phase": 2.5, "detune": 0.8 },
  "frame_ms": 20
}
```

**Cylon** — one red blob, ping-ponging.

```json
{
  "palette": [[255,0,0]],
  "sample":  { "mode": "fixed" },
  "level":   { "mode": "blob", "min": 0, "max": 1,
               "speed": 0.4, "width": 0.03, "trail": 0.25, "pingpong": true },
  "frame_ms": 20
}
```

**Confetti** — random colours, struck and faded.

```json
{
  "palette": [[255,0,0], [255,180,0], [0,255,120], [0,140,255], [200,0,255]],
  "sample":  { "mode": "random" },
  "level":   { "mode": "impulse", "min": 0, "max": 1, "rate": 0.6, "decay": 0.92 },
  "frame_ms": 20
}
```

---

## What this deliberately cannot do

**Fire.** `effectFire()` diffuses heat between neighbouring pixels — a pixel's
colour depends on its neighbours' *previous* values, not on `(p, t)` alone. That
is a genuinely different kind of effect, and it stays compiled. Bending a
stateless engine around one effect would cost more than it saves.

**Music.** LIFX's music mode needs an audio signal and an FFT. No palette gets
you there. It is buildable — the Pi could listen and publish a level over
MQTT — but it is a different project with a different shape, and folding it in
here would muddy both.

---

## Matching LIFX

Worth stating plainly, because it reframes the work: **LIFX does not have forty
effects.** It has about four motions and a large library of palettes.

- **Move** is a scroll
- **Morph** is `sample: noise`
- **Flame** is fire
- Exciting, Calm, Serene, Dream, Spooky, Tranquil — these are *themes*, which is
  to say palettes riding those same motions

So matching it is not reimplementing forty algorithms. It is implementing four
and then collecting colours.

---

## Adding an effect

1. Write the recipe (the preview in the web UI runs the same maths in the
   browser — tune it there rather than by reflashing)
2. Save it
3. It appears on every strip in the house, including ones built before the
   effect existed

No firmware build. No cable.
