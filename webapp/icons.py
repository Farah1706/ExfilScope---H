"""Navigation and control glyphs drawn for the platform (original path data, 24 x 24 grid).

Evidence glyphs come from dashboard/icons.py (Lucide, ISC licence) so both interfaces use
the same marks for outcomes, ledgers and the proxy.
"""

from dashboard.icons import PATHS

EXTRA = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
    "flask": '<path d="M9 3h6"/><path d="M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 '
             '1.3-2L14 9V3"/><path d="M7.5 15h9"/>',
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "pulse": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "chart": '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M2 20h20"/>',
    "book": '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5z"/>'
            '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>',
    "close": '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 '
            '.9-1 1.6V14"/><path d="M12 17.5h.01"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    "shield": '<path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "doc": '<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4"/><path d="M9 13h6"/><path d="M9 17h6"/>',
}
ICONS = {**PATHS, **EXTRA}
