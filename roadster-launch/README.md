# Tesla Roadster — 15 s launch film

Apple-keynote-style teaser: a cold open line, four photo shots with slow camera
moves (push-ins and pans), a light sweep across the car, spec cards, a silver
"Roadster" end title, and a synthesized score with impacts on every cut.

| Time        | Shot                           | Card                              |
|-------------|--------------------------------|-----------------------------------|
| 0.0 – 1.6   | black                          | The quickest car / ever made.     |
| 1.6 – 5.0   | `images/01` hero, light sweep  | —                                 |
| 5.0 – 7.5   | `images/02` detail             | 0–60 mph **1.9 s**                |
| 7.5 – 10.0  | `images/03` profile            | Range **620 mi**                  |
| 10.0 – 12.6 | `images/04` rear / interior    | Top speed **250+ mph**            |
| 12.6 – 15.0 | black                          | TESLA **Roadster** Coming soon.   |

The specs are the targets Tesla announced for the Roadster.

## Usage

1. Put real photos in `images/` as `01.jpg` to `04.jpg` (landscape, 2000 px wide or more),
   or run `python3 fetch_images.py` to pull freely licensed ones from Wikimedia Commons.
2. `python3 render.py` writes `out/roadster_launch.mp4` (1920×1080, 30 fps, H.264 + AAC).
   Add `--vertical` for a 1080×1920 Reels/TikTok version.

Any missing photo renders as a labelled placeholder.
