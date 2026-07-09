# Bundled fonts

**Prompt** (Regular, SemiBold) by Cadson Demak — the Thai typeface this
project's web UI already uses (`font-family: 'Prompt'` throughout the
static pages). Bundled here so the Employee Hub rich-menu image renderer
(`app/services/staff_oa_images.py`) can draw Thai labels deterministically
on any machine/container, including CI, without depending on system fonts.

Licensed under the **SIL Open Font License 1.1** — see [OFL.txt](OFL.txt)
(extracted verbatim from the font's embedded license record). The OFL
permits bundling and redistribution as long as the license file
accompanies the fonts, which is why OFL.txt lives next to them.

Canonical source: <https://fonts.google.com/specimen/Prompt>
