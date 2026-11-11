# Third-party notices

This file covers the third-party material distributed with ExfilScope's own source: icon
path data and font files. Python dependencies are installed from the lock files and keep
their own licences; they are not redistributed here.

## Lucide icons

`dashboard/icons.py` embeds SVG path data from [Lucide](https://lucide.dev). The unified
platform reuses that table (`webapp/icons.py` adds a few original glyphs) and serves it as
`icons.json`, including in the static public build.

```text
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT).
All other copyright (c) for Lucide are held by Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

## Fonts

The unified platform bundles two font families in `webapp/static/fonts/`, served locally by
the platform and copied into the static public build. Nothing is fetched from Google Fonts
or any other host.

| Files | Family | Licence |
|---|---|---|
| `InterVariable.woff2` | Inter 4.1 | SIL Open Font License 1.1, full text in `webapp/static/fonts/Inter-OFL.txt` |
| `JetBrainsMono-Regular.woff2`, `-Medium.woff2`, `-SemiBold.woff2` | JetBrains Mono 2.304 | SIL Open Font License 1.1, full text in `webapp/static/fonts/JetBrainsMono-OFL.txt` |

Sources and SHA-256 values are listed in `webapp/static/fonts/README.md`. The fonts are
redistributed unmodified, with their licences, and are not sold on their own.

The Streamlit dashboard (`.streamlit/config.toml`) names Inter and JetBrains Mono but loads
no font files: it uses them only when installed on the computer and otherwise falls back to
system fonts (Segoe UI, Cascadia Mono, Consolas).

## Font sources

# Bundled fonts

The interface uses Inter for all text and JetBrains Mono only for identifiers, hashes and
JSON. Both are bundled here and served by the local service (`/fonts.css`), so the platform
works offline and requests no font from the network. If a file is missing, an installed copy
is used and then the system stacks (Segoe UI, Cascadia Mono/Consolas).

| File | Family and weights | Source | Licence |
|---|---|---|---|
| `InterVariable.woff2` | Inter, variable 100–900 | `web/` in the official release `Inter-4.1.zip` (https://github.com/rsms/inter/releases/tag/v4.1) | SIL Open Font License 1.1, `Inter-OFL.txt` |
| `JetBrainsMono-Regular.woff2`, `-Medium.woff2`, `-SemiBold.woff2` | JetBrains Mono 400, 500, 600 | `fonts/webfonts/` in the official release `JetBrainsMono-2.304.zip` (https://github.com/JetBrains/JetBrainsMono/releases/tag/v2.304) | SIL Open Font License 1.1, `JetBrainsMono-OFL.txt` |

SHA-256 of the archives as downloaded on 1 November 2026: `Inter-4.1.zip`
`9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`,
`JetBrainsMono-2.304.zip` `6f6376c6ed2960ea8a963cd7387ec9d76e3f629125bc33d1fdcd7eb7012f7bbf`.

| File | SHA-256 |
|---|---|
| `InterVariable.woff2` | `693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3` |
| `JetBrainsMono-Regular.woff2` | `a9cb1cd82332b23a47e3a1239d25d13c86d16c4220695e34b243effa999f45f2` |
| `JetBrainsMono-Medium.woff2` | `086c48dfbea9ddaff1320f7e09399b8e2924e88ce67453721255db3bdbb5a353` |
| `JetBrainsMono-SemiBold.woff2` | `918edad542a1da608fd2ba8daebaff9ac802309103fe760eed465b8b4e47faf1` |

The Streamlit fallback (`dashboard/`) names the same families but cannot serve these files;
it uses them only when they are installed on the computer.
