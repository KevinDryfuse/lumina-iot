"""
The built-in effects, expressed as recipes.

These are the twelve that used to be compiled into the firmware, translated
into the two-slot form described in docs/RECIPES.md, plus a set of theme
palettes riding the same motions.

Seeded on start-up and INSERTED ONLY IF MISSING. Never updated in place: once
one of these has been tuned by hand in the studio, a redeploy must not quietly
undo that. Delete a row to get the original back.

Breathing, chase, sparkle, cylon and strobe use the palette stop "device",
which resolves at render time to whatever colour the strip is set to - so they
behave as they did when they were compiled, and still follow the colour picker.

One honest gap remains, worth knowing before comparing these against the
originals:

  - Rainbow and christmas were written against raw LED indices (hue += 7 per
    LED, alternate every other pixel), so they looked different on strips of
    different lengths. The recipe versions are resolution-independent, which
    means they will not match pixel for pixel on any particular strip. That is
    the intended behaviour rather than a translation error.

Fire is absent on purpose. It diffuses heat between neighbouring pixels, so it
cannot be expressed as a function of (position, time) and stays compiled.
"""

# Full spectrum, used by anything that wants "all the colours".
SPECTRUM = [[255, 0, 0], [255, 160, 0], [200, 255, 0], [0, 255, 60],
            [0, 200, 255], [40, 0, 255], [200, 0, 255]]

BUILTIN = {
    # ---- the originals ----
    "rainbow": {
        "label": "RAINBOW", "category": "standard",
        "recipe": {
            "palette": SPECTRUM,
            "sample": {"mode": "scroll", "span": 1.0, "speed": 0.2},
            "level": {"mode": "solid", "max": 1.0},
            "frame_ms": 20,
        },
    },
    "breathing": {
        "label": "PULSE", "category": "standard",
        "recipe": {
            "palette": ["device"],
            "sample": {"mode": "fixed"},
            # beatsin8(12, 20, 255) - 12 BPM is 0.2 Hz, floor 20/255.
            "level": {"mode": "wave", "min": 0.08, "max": 1.0, "speed": 0.2},
            "frame_ms": 20,
        },
    },
    "chase": {
        "label": "CHASE", "category": "standard",
        "recipe": {
            "palette": ["device"],
            "sample": {"mode": "fixed"},
            # fadeToBlackBy(40) per frame is roughly a quarter-strip tail.
            "level": {"mode": "blob", "min": 0, "max": 1.0, "speed": 0.5,
                      "width": 0.015, "trail": 0.22, "pingpong": False},
            "frame_ms": 20,
        },
    },
    "sparkle": {
        "label": "SPARKLE", "category": "standard",
        "recipe": {
            "palette": ["device"],
            "sample": {"mode": "fixed"},
            # random8() < 80 is a 0.31 strike rate; fadeToBlackBy(20) is 0.92.
            "level": {"mode": "impulse", "min": 0, "max": 1.0,
                      "rate": 0.31, "decay": 0.92},
            "frame_ms": 30,
        },
    },
    "confetti": {
        "label": "CONFETTI", "category": "party",
        "recipe": {
            "palette": SPECTRUM,
            "sample": {"mode": "random"},
            "level": {"mode": "impulse", "min": 0, "max": 1.0,
                      "rate": 0.6, "decay": 0.96},
            "frame_ms": 20,
        },
    },
    "cylon": {
        "label": "CYLON", "category": "party",
        "recipe": {
            "palette": ["device"],
            "sample": {"mode": "fixed"},
            "level": {"mode": "blob", "min": 0, "max": 1.0, "speed": 0.4,
                      "width": 0.02, "trail": 0.25, "pingpong": True},
            "frame_ms": 20,
        },
    },
    "strobe": {
        "label": "STROBE", "category": "party",
        "recipe": {
            "palette": ["device"],
            "sample": {"mode": "fixed"},
            # Toggled every 80ms in the original: 6.25 Hz.
            "level": {"mode": "square", "min": 0, "max": 1.0, "speed": 6.25},
            "frame_ms": 20,
        },
    },
    "ocean": {
        "label": "OCEAN", "category": "ambient",
        "recipe": {
            "palette": [[0, 40, 90], [0, 120, 200], [80, 220, 255]],
            "sample": {"mode": "position", "span": 1.0},
            # beatsin8(6 + (i%5), 100, 255, ...) - slow, floor at 100/255.
            "level": {"mode": "wave", "min": 0.39, "max": 1.0,
                      "speed": 0.5, "phase": 2.5, "detune": 0.8},
            "frame_ms": 20,
        },
    },
    "aurora": {
        "label": "AURORA", "category": "ambient",
        "recipe": {
            "palette": [[0, 255, 60], [0, 200, 180], [0, 120, 255], [40, 220, 140]],
            "sample": {"mode": "scroll", "span": 2.0, "speed": 0.05},
            "level": {"mode": "wave", "min": 0.2, "max": 1.0,
                      "speed": 0.35, "phase": 1.5, "detune": 1.0},
            "frame_ms": 30,
        },
    },
    "candle": {
        "label": "CANDLE", "category": "ambient",
        "recipe": {
            "palette": [[255, 110, 0], [255, 160, 30]],
            "sample": {"mode": "noise", "scale": 2.0, "speed": 0.4},
            # random8(180, 255) in the original - a shallow, fast flicker.
            "level": {"mode": "flicker", "min": 0.7, "max": 1.0},
            "frame_ms": 50,
        },
    },
    "christmas": {
        "label": "XMAS", "category": "holiday",
        "recipe": {
            # Stops are REPEATED on purpose. The palette interpolates, so red
            # straight into green spends half its length in the muddy browns
            # between them - which is what made the first version of this look
            # washed out rather than festive. Doubling each colour gives flat
            # bands with short transitions instead.
            "palette": [[200, 0, 0], [200, 0, 0], [0, 140, 0], [0, 140, 0]],
            "sample": {"mode": "position", "span": 6.0},
            # High floor so the bands stay lit, heavy detune so pixels shimmer
            # out of step - the twinkle the original got from random8().
            "level": {"mode": "wave", "min": 0.55, "max": 1.0,
                      "speed": 0.5, "phase": 9.0, "detune": 2.0},
            "frame_ms": 30,
        },
    },
    "candycane": {
        "label": "CANDY CANE", "category": "holiday",
        "recipe": {
            "palette": [[220, 0, 0], [220, 0, 0], [255, 255, 255], [255, 255, 255]],
            "sample": {"mode": "scroll", "span": 5.0, "speed": 0.12},
            "level": {"mode": "solid", "max": 1.0},
            "frame_ms": 20,
        },
    },
    "twinkle": {
        "label": "TWINKLE", "category": "holiday",
        "recipe": {
            "palette": [[255, 60, 40], [40, 200, 60], [255, 220, 120]],
            "sample": {"mode": "random"},
            "level": {"mode": "impulse", "min": 0.05, "max": 1.0,
                      "rate": 0.5, "decay": 0.94},
            "frame_ms": 25,
        },
    },
    "usa": {
        "label": "USA", "category": "holiday",
        "recipe": {
            "palette": [[220, 0, 0], [255, 255, 255], [0, 40, 200]],
            "sample": {"mode": "position", "span": 1.0},
            "level": {"mode": "wave", "min": 0.75, "max": 1.0,
                      "speed": 0.3, "phase": 3.0, "detune": 1.0},
            "frame_ms": 30,
        },
    },

    # ---- ambient: slow, flowing, meant for a dark room ----
    #
    # Deliberately dimmer than the themes below. These are for a room lit by
    # monitors, where a strip at full brightness stops being ambient and starts
    # being a lamp. The brightness ceilings sit well under 1.0 on purpose; the
    # strip's own brightness control still scales on top of that.
    "nebula": {
        "label": "NEBULA", "category": "ambient",
        "recipe": {
            "palette": [[16, 0, 48], [70, 0, 130], [160, 40, 200],
                        [40, 0, 100], [8, 0, 32]],
            "sample": {"mode": "noise", "scale": 2.2, "speed": 0.06},
            "level": {"mode": "wave", "min": 0.25, "max": 0.85,
                      "speed": 0.12, "phase": 1.6, "detune": 1.3},
            "frame_ms": 30,
        },
    },
    "cryo": {
        "label": "CRYO", "category": "ambient",
        "recipe": {
            "palette": [[0, 30, 70], [70, 150, 210], [190, 230, 255], [20, 80, 140]],
            "sample": {"mode": "noise", "scale": 1.6, "speed": 0.05},
            "level": {"mode": "wave", "min": 0.3, "max": 0.9,
                      "speed": 0.1, "phase": 1.0, "detune": 0.9},
            "frame_ms": 30,
        },
    },
    "abyss": {
        "label": "ABYSS", "category": "ambient",
        "recipe": {
            # Bioluminescence: mostly near-black, with slow teal blooms.
            "palette": [[0, 6, 16], [0, 55, 75], [0, 170, 150], [0, 25, 45]],
            "sample": {"mode": "noise", "scale": 2.8, "speed": 0.04},
            "level": {"mode": "wave", "min": 0.12, "max": 0.8,
                      "speed": 0.09, "phase": 2.2, "detune": 1.5},
            "frame_ms": 35,
        },
    },
    "nightshift": {
        "label": "NIGHTSHIFT", "category": "ambient",
        "recipe": {
            # Warm, very dim, no blue at all. For working late without wrecking
            # your eyes - the ceiling of 0.45 is the entire point of this one.
            "palette": [[60, 20, 0], [120, 50, 8], [80, 30, 4]],
            "sample": {"mode": "noise", "scale": 1.2, "speed": 0.03},
            "level": {"mode": "wave", "min": 0.22, "max": 0.45,
                      "speed": 0.06, "phase": 0.7, "detune": 0.8},
            "frame_ms": 40,
        },
    },
    "ember": {
        "label": "EMBER", "category": "ambient",
        "recipe": {
            # The colours of fire without its physics: a slow glow rather than a
            # flicker, so it reads as coals rather than flames.
            "palette": [[35, 0, 0], [130, 22, 0], [210, 65, 0], [70, 8, 0]],
            "sample": {"mode": "noise", "scale": 2.0, "speed": 0.07},
            "level": {"mode": "wave", "min": 0.18, "max": 0.7,
                      "speed": 0.15, "phase": 1.2, "detune": 1.4},
            "frame_ms": 30,
        },
    },

    # ---- sci-fi: harder edges and more motion, for a room full of screens ----
    "tron": {
        "label": "TRON", "category": "scifi",
        "recipe": {
            # Repeated stops give hard bands instead of a gradient. The look
            # depends on that edge staying sharp.
            "palette": [[0, 8, 16], [0, 8, 16], [0, 247, 255], [0, 247, 255]],
            "sample": {"mode": "scroll", "span": 4.0, "speed": 0.22},
            "level": {"mode": "solid", "max": 0.8},
            "frame_ms": 20,
        },
    },
    "reactor": {
        "label": "REACTOR", "category": "scifi",
        "recipe": {
            # Low detune on purpose. This one should pulse in UNISON, like
            # something powering up, where aurora should shimmer out of step.
            # Same parameter, opposite intent.
            "palette": [[0, 16, 24], [0, 110, 125], [70, 250, 225], [0, 80, 100]],
            "sample": {"mode": "scroll", "span": 1.5, "speed": 0.04},
            "level": {"mode": "wave", "min": 0.2, "max": 0.95,
                      "speed": 0.28, "phase": 0.6, "detune": 0.3},
            "frame_ms": 25,
        },
    },
    "synthwave": {
        "label": "SYNTHWAVE", "category": "scifi",
        "recipe": {
            "palette": [[255, 0, 130], [110, 0, 210], [0, 190, 255], [55, 0, 110]],
            "sample": {"mode": "scroll", "span": 2.0, "speed": 0.08},
            "level": {"mode": "wave", "min": 0.35, "max": 0.95,
                      "speed": 0.2, "phase": 1.4, "detune": 1.0},
            "frame_ms": 25,
        },
    },
    "datastream": {
        "label": "DATASTREAM", "category": "scifi",
        "recipe": {
            "palette": [[0, 16, 8], [0, 255, 110], [0, 55, 35], [0, 8, 4]],
            "sample": {"mode": "scroll", "span": 3.0, "speed": 0.55},
            "level": {"mode": "wave", "min": 0.25, "max": 0.9,
                      "speed": 1.1, "phase": 4.0, "detune": 1.8},
            "frame_ms": 20,
        },
    },
    "sonar": {
        "label": "SONAR", "category": "scifi",
        "recipe": {
            # One sweep, one direction, long tail. pingpong false so it always
            # travels the same way: a scan, not a pendulum.
            "palette": [[0, 255, 180]],
            "sample": {"mode": "fixed"},
            "level": {"mode": "blob", "min": 0.02, "max": 0.85, "speed": 0.15,
                      "width": 0.015, "trail": 0.5, "pingpong": False},
            "frame_ms": 20,
        },
    },
    "starfield": {
        "label": "STARFIELD", "category": "scifi",
        "recipe": {
            "palette": [[255, 255, 255], [170, 195, 255], [255, 235, 195]],
            "sample": {"mode": "random"},
            "level": {"mode": "impulse", "min": 0.0, "max": 0.85,
                      "rate": 0.22, "decay": 0.9},
            "frame_ms": 30,
        },
    },

    # ---- the rest of the calendar ----
    "halloween": {
        "label": "HALLOWEEN", "category": "holiday",
        "recipe": {
            "palette": [[255, 70, 0], [255, 70, 0], [80, 0, 130], [80, 0, 130]],
            "sample": {"mode": "position", "span": 5.0},
            "level": {"mode": "wave", "min": 0.35, "max": 1.0,
                      "speed": 0.35, "phase": 7.0, "detune": 1.6},
            "frame_ms": 30,
        },
    },
    "thanksgiving": {
        "label": "THANKSGIVING", "category": "holiday",
        "recipe": {
            "palette": [[140, 45, 0], [215, 125, 18], [110, 62, 8], [190, 85, 0]],
            "sample": {"mode": "noise", "scale": 2.0, "speed": 0.06},
            "level": {"mode": "wave", "min": 0.45, "max": 1.0,
                      "speed": 0.15, "phase": 1.2, "detune": 1.0},
            "frame_ms": 30,
        },
    },
    "newyear": {
        "label": "NEW YEAR", "category": "holiday",
        "recipe": {
            "palette": [[255, 200, 60], [255, 255, 255], [255, 165, 0]],
            "sample": {"mode": "random"},
            "level": {"mode": "impulse", "min": 0.04, "max": 1.0,
                      "rate": 0.65, "decay": 0.9},
            "frame_ms": 20,
        },
    },
    "valentine": {
        "label": "VALENTINE", "category": "holiday",
        "recipe": {
            "palette": [[255, 0, 80], [255, 120, 180], [170, 0, 55], [255, 60, 120]],
            "sample": {"mode": "noise", "scale": 1.8, "speed": 0.07},
            "level": {"mode": "wave", "min": 0.4, "max": 1.0,
                      "speed": 0.18, "phase": 1.5, "detune": 1.1},
            "frame_ms": 30,
        },
    },
    "stpatrick": {
        "label": "ST PATRICK", "category": "holiday",
        "recipe": {
            "palette": [[0, 110, 0], [0, 200, 60], [110, 215, 40], [0, 85, 28]],
            "sample": {"mode": "scroll", "span": 3.0, "speed": 0.1},
            "level": {"mode": "wave", "min": 0.45, "max": 1.0,
                      "speed": 0.2, "phase": 2.0, "detune": 1.2},
            "frame_ms": 25,
        },
    },
    "easter": {
        "label": "EASTER", "category": "holiday",
        "recipe": {
            "palette": [[255, 175, 200], [175, 228, 255], [215, 255, 185],
                        [255, 240, 165]],
            "sample": {"mode": "noise", "scale": 1.5, "speed": 0.06},
            "level": {"mode": "wave", "min": 0.55, "max": 1.0,
                      "speed": 0.14, "phase": 1.0, "detune": 0.9},
            "frame_ms": 30,
        },
    },

    # ---- themes ----
    #
    # These are what LIFX actually ships. Its library is not forty algorithms;
    # it is a few motions and a lot of palettes, nearly all of them riding the
    # same slow noise drift that its app calls Morph. So these are one recipe
    # shape with the colours swapped, which is the clearest possible
    # demonstration of why the engine is built the way it is.
    "nature": {
        "label": "NATURE", "category": "theme",
        "recipe": {
            "palette": [[20, 120, 20], [90, 170, 40], [220, 200, 90],
                        [40, 140, 90], [10, 90, 50]],
            "sample": {"mode": "noise", "scale": 2.5, "speed": 0.15},
            "level": {"mode": "wave", "min": 0.55, "max": 1.0,
                      "speed": 0.2, "phase": 1.0, "detune": 1.0},
            "frame_ms": 30,
        },
    },
    "space": {
        "label": "SPACE", "category": "theme",
        "recipe": {
            "palette": [[5, 0, 40], [60, 0, 140], [140, 40, 220],
                        [0, 80, 200], [255, 255, 255]],
            "sample": {"mode": "noise", "scale": 3.0, "speed": 0.08},
            "level": {"mode": "wave", "min": 0.25, "max": 1.0,
                      "speed": 0.15, "phase": 2.0, "detune": 1.4},
            "frame_ms": 30,
        },
    },
    "dream": {
        "label": "DREAM", "category": "theme",
        "recipe": {
            "palette": [[255, 140, 200], [160, 120, 255], [120, 220, 255],
                        [255, 200, 160]],
            "sample": {"mode": "noise", "scale": 1.8, "speed": 0.1},
            "level": {"mode": "wave", "min": 0.45, "max": 1.0,
                      "speed": 0.18, "phase": 1.2, "detune": 1.1},
            "frame_ms": 30,
        },
    },
    "serene": {
        "label": "SERENE", "category": "theme",
        "recipe": {
            "palette": [[120, 200, 220], [180, 230, 240], [90, 150, 200],
                        [200, 220, 210]],
            "sample": {"mode": "noise", "scale": 1.5, "speed": 0.06},
            "level": {"mode": "wave", "min": 0.6, "max": 1.0,
                      "speed": 0.12, "phase": 0.8, "detune": 0.9},
            "frame_ms": 40,
        },
    },
    "spooky": {
        "label": "SPOOKY", "category": "theme",
        "recipe": {
            "palette": [[255, 90, 0], [90, 0, 140], [20, 20, 20], [140, 200, 0]],
            "sample": {"mode": "noise", "scale": 2.2, "speed": 0.12},
            "level": {"mode": "wave", "min": 0.2, "max": 1.0,
                      "speed": 0.25, "phase": 2.4, "detune": 1.6},
            "frame_ms": 30,
        },
    },
    "warming": {
        "label": "WARMING", "category": "theme",
        "recipe": {
            "palette": [[255, 100, 20], [255, 170, 60], [220, 60, 10],
                        [255, 210, 130]],
            "sample": {"mode": "noise", "scale": 2.0, "speed": 0.1},
            "level": {"mode": "wave", "min": 0.5, "max": 1.0,
                      "speed": 0.16, "phase": 1.4, "detune": 1.0},
            "frame_ms": 30,
        },
    },
}


def seed_effects(SessionLocal, Effect):
    """Insert any built-in that is not already present.

    Insert-only. A row edited in the studio survives every redeploy; deleting it
    restores the original on the next start.
    """
    db = SessionLocal()
    try:
        existing = {e.name for e in db.query(Effect.name).all()}
        added = 0
        for name, spec in BUILTIN.items():
            if name in existing:
                continue
            db.add(Effect(name=name, label=spec["label"],
                          category=spec["category"], recipe=spec["recipe"]))
            added += 1
        if added:
            db.commit()
        print(f"Effects: {added} built-in seeded, {len(existing)} already present")
    finally:
        db.close()
