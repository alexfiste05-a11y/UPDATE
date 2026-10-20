#!/usr/bin/env python3
"""Render a 15 s Apple-keynote-style launch film for the Tesla Roadster.

Real photos go in images/01.jpg .. images/04.jpg (see README.md).
Missing photos render as labelled placeholders so the edit can be previewed.

    python3 render.py            # -> out/roadster_launch.mp4 (1920x1080, 30 fps)
    python3 render.py --vertical # -> out/roadster_launch_9x16.mp4 (1080x1920)
"""
import argparse
import math
import os
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
DUR = 15.0
SR = 48000
FONT_DIR = "/usr/share/fonts/opentype/inter"


def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


# ---------------------------------------------------------------- easing
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_io(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 4


def ramp(t, t0, t1):
    return clamp((t - t0) / (t1 - t0)) if t1 > t0 else float(t >= t0)


# ---------------------------------------------------------------- timeline
# Each shot: photo, start, end, zoom from/to, pan (fraction of frame) from/to.
SHOTS = [
    dict(img="01", t0=1.6, t1=5.0, z=(1.18, 1.04), p=((0.00, 0.02), (0.00, 0.00)), sweep=True),
    dict(img="02", t0=5.0, t1=7.5, z=(1.10, 1.22), p=((-0.03, 0.0), (0.03, 0.0))),
    dict(img="03", t0=7.5, t1=10.0, z=(1.08, 1.08), p=((0.05, 0.0), (-0.05, 0.0))),
    dict(img="04", t0=10.0, t1=12.6, z=(1.22, 1.06), p=((0.0, -0.02), (0.0, 0.01))),
]
# Text cards: (start, end, lines). Specs are Tesla's announced targets.
CAPTIONS = [
    (0.25, 1.75, [("The quickest car", "InterDisplay-SemiBold.otf", 64)]),
    (0.25, 1.75, [("ever made.", "InterDisplay-SemiBold.otf", 64)]),
    (5.25, 7.30, [("0–60 mph", "InterDisplay-Medium.otf", 40), ("1.9 s", "InterDisplay-Bold.otf", 150)]),
    (7.75, 9.80, [("Range", "InterDisplay-Medium.otf", 40), ("620 mi", "InterDisplay-Bold.otf", 150)]),
    (10.25, 12.40, [("Top speed", "InterDisplay-Medium.otf", 40), ("250+ mph", "InterDisplay-Bold.otf", 150)]),
]
HITS = [1.6, 5.0, 7.5, 10.0, 12.6]


# ---------------------------------------------------------------- assets
def load_photo(key, W, H):
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = os.path.join(HERE, "images", f"{key}.{ext}")
        if os.path.exists(p):
            im = Image.open(p).convert("RGB")
            # cover-fit at 1.3x so zoom/pan never exposes edges or softens
            s = max(W / im.width, H / im.height) * 1.3
            return im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS), True
    # placeholder: studio sweep + label, clearly not a real photo
    w, h = int(W * 1.3), int(H * 1.3)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((x - w / 2) / w) ** 2 + ((y - h * 0.62) / h) ** 2)
    g = np.clip(0.30 - d * 0.45, 0.02, 1)
    arr = np.dstack([g * 255, g * 258, g * 265]).clip(0, 255).astype(np.uint8)
    im = Image.fromarray(arr)
    dr = ImageDraw.Draw(im)
    dr.text((w / 2, h / 2), f"PHOTO {key}  →  images/{key}.jpg", font=font("Inter-Medium.otf", int(H * 0.035)),
             fill=(150, 150, 155), anchor="mm")
    return im, False


def render_text_block(lines, W, gradient=False):
    """Stack lines centred; return RGBA image."""
    imgs = []
    for txt, fnt, size in lines:
        f = font(fnt, size)
        bb = f.getbbox(txt)
        tw, th = bb[2] - bb[0] + 40, int(size * 1.25)
        mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(mask).text((20 - bb[0], int(size * 0.1)), txt, font=f, fill=255)
        if gradient:
            # brushed-silver vertical gradient, Apple wordmark style
            yy = np.linspace(0, 1, th)[:, None]
            col = np.clip(255 - 95 * yy ** 1.4, 0, 255)
            rgb = np.dstack([np.repeat(col, tw, 1)] * 3).astype(np.uint8)
            tile = Image.fromarray(rgb).convert("RGBA")
        else:
            secondary = size < 60
            c = (134, 134, 139) if secondary else (245, 245, 247)
            tile = Image.new("RGBA", (tw, th), c + (255,))
        tile.putalpha(mask)
        imgs.append(tile)
    h = sum(i.height for i in imgs)
    out = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    y = 0
    for i in imgs:
        out.alpha_composite(i, ((W - i.width) // 2, y))
        y += i.height
    return out


# ---------------------------------------------------------------- frame ops
def kenburns(src, W, H, zoom, pan):
    # affine maps output pixel -> source pixel
    sw, sh = src.width, src.height
    scale = (sw / 1.3) / W / zoom
    cx = sw / 2 + pan[0] * sw / 1.3
    cy = sh / 2 + pan[1] * sh / 1.3
    a, e = scale, scale
    c = cx - a * W / 2
    f = cy - e * H / 2
    return src.transform((W, H), Image.AFFINE, (a, 0, c, 0, e, f), resample=Image.BICUBIC)


def grade(arr):
    """Cinematic grade: gentle S-curve, cool shadows, warm highlights."""
    x = arr / 255.0
    x = x * x * (3 - 2 * x) * 0.35 + x * 0.65
    lum = x.mean(axis=2, keepdims=True)
    x = x + (0.5 - lum) * np.array([-0.012, 0.0, 0.025]) * 2 * (1 - lum)
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vertical", action="store_true")
    args = ap.parse_args()
    W, H = (1080, 1920) if args.vertical else (1920, 1080)
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)
    name = "roadster_launch_9x16" if args.vertical else "roadster_launch"

    photos = {s["img"]: load_photo(s["img"], W, H) for s in SHOTS}
    missing = [k for k, (_, ok) in photos.items() if not ok]
    if missing:
        print("placeholders used for:", ", ".join(missing))

    ks = H / 1080
    cap_imgs = []
    for t0, t1, lines in CAPTIONS:
        lines = [(t, f, int(sz * ks * (0.85 if args.vertical and sz > 100 else 1))) for t, f, sz in lines]
        cap_imgs.append((t0, t1, render_text_block(lines, W)))
    # opening line is two separate cards revealed in sequence
    wordmark = render_text_block([("Roadster", "InterDisplay-SemiBold.otf", int(200 * ks * (0.8 if args.vertical else 1)))], W, True)
    brand = render_text_block([("TESLA", "InterDisplay-Medium.otf", int(30 * ks))], W)
    tagline = render_text_block([("Coming soon.", "InterDisplay-Medium.otf", int(36 * ks))], W)

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vig = 1 - 0.55 * (((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.8)) ** 2)
    vig = np.clip(vig, 0, 1)[..., None]
    rng = np.random.default_rng(7)
    grains = [rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32) for _ in range(6)]

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-i", os.path.join(out_dir, "score.wav"),
         "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", "256k", "-shortest", os.path.join(out_dir, name + ".mp4")],
        stdin=subprocess.PIPE)

    nframes = int(DUR * FPS)
    for fi in range(nframes):
        t = fi / FPS
        frame = np.zeros((H, W, 3), np.float32)

        for sh in SHOTS:
            if not (sh["t0"] - 0.2 <= t < sh["t1"] + 0.2):
                continue
            u = ease_io(ramp(t, sh["t0"], sh["t1"]))
            z = sh["z"][0] + (sh["z"][1] - sh["z"][0]) * u
            p = [sh["p"][0][i] + (sh["p"][1][i] - sh["p"][0][i]) * u for i in range(2)]
            img = grade(np.asarray(kenburns(photos[sh["img"]][0], W, H, z, p), np.float32))
            # exposure: first shot rises out of darkness, others dip through black
            if sh is SHOTS[0]:
                expo = ease_out(ramp(t, sh["t0"], sh["t0"] + 1.4)) ** 1.6
            else:
                expo = ease_out(ramp(t, sh["t0"] - 0.05, sh["t0"] + 0.35))
            expo *= 1 - ease_io(ramp(t, sh["t1"] - 0.25, sh["t1"] + 0.05))
            if sh.get("sweep"):
                # diagonal specular sweep across the body
                pos = -0.3 + 1.6 * ease_io(ramp(t, sh["t0"] + 0.6, sh["t0"] + 2.6))
                band = np.exp(-(((xx / W) * 0.8 + (yy / H) * 0.35 - pos) / 0.06) ** 2)[..., None]
                img = img + band * 0.22 * img.mean(axis=2, keepdims=True) ** 0.5
            frame = np.maximum(frame, img * expo)

        # caption cards: blur-in rise, fade out
        def put(layer, t0, t1, yc, rise=24):
            nonlocal frame
            a_in = ease_out(ramp(t, t0, t0 + 0.6))
            a_out = 1 - ease_io(ramp(t, t1 - 0.35, t1))
            a = a_in * a_out
            if a <= 0.002:
                return
            lay = layer
            blur = (1 - a_in) * 10 * ks
            if blur > 0.3:
                lay = lay.filter(ImageFilter.GaussianBlur(blur))
            arr = np.asarray(lay, np.float32)
            y0 = int(yc - arr.shape[0] / 2 + (1 - a_in) * rise * ks)
            ys, ye = max(0, y0), min(H, y0 + arr.shape[0])
            if ye <= ys:
                return
            seg = arr[ys - y0:ye - y0]
            al = seg[..., 3:4] / 255 * a
            frame[ys:ye] = frame[ys:ye] * (1 - al) + seg[..., :3] / 255 * al

        c_y = H * (0.80 if not args.vertical else 0.74)
        put(cap_imgs[0][2], 0.25, 1.75, H / 2 - 40 * ks)
        put(cap_imgs[1][2], 0.65, 1.75, H / 2 + 40 * ks)
        for t0, t1, im in cap_imgs[2:]:
            if t0 - 0.1 <= t <= t1:
                band = np.clip((yy[..., None] / H - 0.55) / 0.45, 0, 1) ** 1.5 * 0.7
                frame *= 1 - band * ease_out(ramp(t, t0, t0 + 0.5)) * (1 - ease_io(ramp(t, t1 - 0.35, t1)))
                put(im, t0, t1, c_y)

        # end card
        if t >= 12.6:
            put(wordmark, 12.85, 99, H / 2 - 10 * ks, rise=36)
            put(brand, 13.35, 99, H / 2 - 150 * ks * (0.8 if args.vertical else 1), rise=12)
            put(tagline, 13.75, 99, H / 2 + 175 * ks * (0.8 if args.vertical else 1), rise=12)
            frame *= 1 - ease_io(ramp(t, 14.55, 15.0))

        if t < 12.6:
            frame = frame * (vig * 0.85 + 0.15)
        g = grains[fi % len(grains)]
        g = np.repeat(np.repeat(g, 2, 0), 2, 1)[..., None]
        frame = frame + g * 0.012 * (0.4 + frame)
        enc.stdin.write((np.clip(frame, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
        if fi % 60 == 0:
            print(f"  frame {fi}/{nframes}", flush=True)

    enc.stdin.close()
    enc.wait()
    print("wrote", os.path.join(out_dir, name + ".mp4"))


# ---------------------------------------------------------------- score
def score(path):
    n = int(DUR * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    out = np.zeros((n, 2))

    def env(t0, a, d):
        x = t - t0
        return np.where(x < 0, 0, np.minimum(x / a, 1) * np.exp(-np.maximum(x - a, 0) / d))

    def lp(x, cutoff):
        k = int(SR / cutoff)
        return np.convolve(x, np.ones(k) / k, "same")

    # sub drone that swells toward the reveal
    drone = (np.sin(2 * np.pi * 36.7 * t) + 0.5 * np.sin(2 * np.pi * 55 * t + np.sin(2 * np.pi * 0.2 * t)))
    swell = np.clip(t / 1.6, 0, 1) ** 2 * 0.25 + np.clip((t - 1.6) / 11, 0, 1) * 0.25
    swell *= np.where(t < 12.6, 1, 0.0)
    out += (drone * swell * 0.18)[:, None]
    # airy pad (detuned fifths), slow chorus in stereo
    for f, pan in ((110, 0.3), (164.8, 0.7), (220.6, 0.4), (329.2, 0.6)):
        tone = np.sin(2 * np.pi * f * t + 0.8 * np.sin(2 * np.pi * 0.13 * t + f))
        a = np.clip((t - 1.4) / 3, 0, 1) * np.where(t < 12.6, 1, 0) * 0.025
        out[:, 0] += tone * a * (1 - pan)
        out[:, 1] += tone * a * pan
    # noise riser into first hit
    riser = lp(rng.normal(0, 1, n), 2500) * np.clip(t / 1.6, 0, 1) ** 3 * (t < 1.6) * 0.35
    out += riser[:, None]
    # pulse: 8ths at 120 bpm between shots
    for k in np.arange(5.0, 12.5, 0.25):
        e = env(k, 0.002, 0.05)
        out += (np.sin(2 * np.pi * 60 * t) * e * 0.16)[:, None]
    # impact hits on every cut
    for i, h in enumerate(HITS):
        x = np.maximum(t - h, 0)
        sweep = np.sin(2 * np.pi * (45 * x + 60 * (1 - np.exp(-x * 25)) / 25))
        big = 1.8 if i == len(HITS) - 1 else 1.0
        out += (sweep * env(h, 0.003, 0.35 * big) * 0.55 * big)[:, None]
        nb = lp(rng.normal(0, 1, n), 4000) * env(h, 0.001, 0.08) * 0.3
        out += np.stack([nb, np.roll(nb, 90)], 1)
    # final boom reverb tail
    ir = rng.normal(0, 1, int(SR * 2.5)) * np.exp(-np.arange(int(SR * 2.5)) / (SR * 0.6))
    hit = np.zeros(n)
    hit[int(12.6 * SR)] = 1
    tail = np.convolve(hit, ir)[:n]
    out += np.stack([lp(tail, 1500), lp(np.roll(tail, 400), 1500)], 1) * 0.04
    # master: fade, soft clip, normalise
    out *= np.clip((DUR - t) / 0.6, 0, 1)[:, None]
    out = np.tanh(out * 1.4)
    out = out / np.abs(out).max() * 0.89
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((out * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    score(os.path.join(HERE, "out", "score.wav"))
    main()
