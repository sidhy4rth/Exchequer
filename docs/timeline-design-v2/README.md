# Exchequer — project timeline (designed version, v2)

The nine A4 pages of [`../Exchequer-Project-Timeline-v2.pdf`](../Exchequer-Project-Timeline-v2.pdf), shown as images
so they display on GitHub. The text version with every date and source is
[`../project-timeline.md`](../project-timeline.md).

![Page 1 — Cover](page-1.png)
![Page 2 — The project in numbers](page-2.png)
![Page 3 — The arc, in ten phases](page-3.png)
![Page 4 — Phases 0–2](page-4.png)
![Page 5 — Phase 3](page-5.png)
![Page 6 — Phases 4–6](page-6.png)
![Page 7 — Phase 7](page-7.png)
![Page 8 — Phase 8, the bug hunt](page-8.png)
![Page 9 — Phase 9 and where it stands](page-9.png)

---

**Source.** `gen.py` writes the nine pages from the figures in `../project-timeline.md`, and `render.py` prints
the PDF and these images with headless Brave: `python3 gen.py && python3 render.py`. v1 (eight pages, up to
the bug hunt) is kept unchanged in [`../timeline-design/`](../timeline-design/). The `*.dc.html` files and `canvas.json` are in Claude Design's canvas format, so the
pages can be opened there, edited and exported with Export PDF → All artboards.
