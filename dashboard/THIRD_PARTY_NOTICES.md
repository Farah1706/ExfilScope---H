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
