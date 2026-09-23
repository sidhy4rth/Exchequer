# Launch film

Two cuts of the Exchequer launch film, built with Hyperframes. No screenshots —
drawn SVG and type only; a single red square is the money and carries every beat.
Narration is the Kokoro "Emma" voice; the music is the film's own score, generated
by `score.py` in each folder, so there is no track to license.

| Folder | Length | What it is |
|---|---|---|
| [`v3-latest/`](v3-latest/brag.mp4) | 43.2 s | **The latest.** Seven beats: the report, the trace, the map, screened, three complaints one operation, the handoff, the stance — then the mark. |
| [`v2-one-red-square/`](v2-one-red-square/brag.mp4) | 37.9 s | The previous cut: v3 without the "three complaints" beat and the team credit. |

Each folder holds `brag.mp4`, the poster frame `brag.jpg`, the storyboard and full
narration script (`brag-plan.md`), and `composition/`, the Hyperframes project it was
rendered from:

```bash
cd v3-latest/composition && npx hyperframes check && npx hyperframes render --quality looks --output ../brag.mp4
```

The figures on screen are from the week of 20 September 2026 (e.g. 407 labels); the
live numbers since then are in [`../project-timeline.md`](../project-timeline.md).
