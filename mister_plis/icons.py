"""Small stroke icons (24×24 grid). Use the name in ``Tool(icon=...)``."""

from markupsafe import Markup

ICONS = {
    "tool": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "table": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
    "chart": '<path d="M3 3v18h18"/><circle cx="8" cy="14" r="1.3"/><circle cx="12" cy="9.5" r="1.3"/><circle cx="16" cy="12.5" r="1.3"/><circle cx="19" cy="6" r="1.3"/>',
    "curve": '<path d="M3 3v18h18"/><path d="M6 17c3 0 4-10 7-10s3.5 6 7 6"/>',
    "cube": '<path d="M12 2.5 3.5 7v10l8.5 4.5 8.5-4.5V7z"/><path d="m3.5 7 8.5 4.5L20.5 7M12 11.5v10"/>',
    "flask": '<path d="M9 3h6M10 3v6.5L4.6 18.4A2 2 0 0 0 6.3 21.5h11.4a2 2 0 0 0 1.7-3.1L14 9.5V3"/><path d="M7.2 15h9.6"/>',
    "beaker": '<path d="M4 3h16M6 3v15a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V3"/><path d="M6 12h12"/>',
    "droplet": '<path d="M12 2.7 6.3 9.6a7 7 0 1 0 11.4 0z"/>',
    "calculator": '<rect x="5" y="2.5" width="14" height="19" rx="2"/><path d="M8.5 6.5h7M8.5 11h.01M12 11h.01M15.5 11h.01M8.5 14.5h.01M12 14.5h.01M15.5 14.5h.01M8.5 18h.01M12 18h3.5"/>',
    "stats": '<path d="M3 21h18"/><path d="M7 3.5v4M7 14v4M17 6.5v3.5M17 15v2.5"/><rect x="5" y="7.5" width="4" height="6.5" rx=".5"/><rect x="15" y="10" width="4" height="5" rx=".5"/>',
    "convert": '<path d="M4 7.5h14l-3.5-3.5M20 16.5H6l3.5 3.5"/>',
    "file": '<path d="M14 2.5H6.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V8z"/><path d="M14 2.5V8h5.5"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "sync": '<path d="M20.5 11A8.5 8.5 0 0 0 5.6 6.4L3.5 8.5M3.5 13a8.5 8.5 0 0 0 14.9 4.6l2.1-2.1"/><path d="M3.5 3.5v5h5M20.5 20.5v-5h-5"/>',
    "book": '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v16H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
    "upload": '<path d="M12 15V3.5m0 0-4.5 4.5M12 3.5 16.5 8"/><path d="M4 15v3.5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V15"/>',
    "download": '<path d="M12 3.5V15m0 0-4.5-4.5M12 15l4.5-4.5"/><path d="M4 15v3.5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V15"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "check": '<path d="m4.5 12.5 5 5 10-11"/>',
    "alert": '<path d="M12 3 2 20.5h20z"/><path d="M12 10v4.5M12 17.5h.01"/>',
    "play": '<path d="M7 4.5v15l12.5-7.5z"/>',
    "branch": '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M18 9c0 5-6 4-11.2 8.4"/>',
    "ruler": '<path d="M3 16.5 16.5 3 21 7.5 7.5 21z"/><path d="m7 12.5 2 2M10 9.5l2 2M13 6.5l2 2"/>',
    "sigma": '<path d="M18 5H6l6.5 7L6 19h12"/>',
    "dna": '<path d="M7 3c0 6 10 6 10 12s-10 3-10 6M17 3c0 6-10 6-10 12s10 3 10 6"/><path d="M8.5 7h7M8.5 17h7"/>',
    "microscope": '<path d="M6 20.5h12M9 17.5h6M12 17.5a6 6 0 0 0 5.5-8.5"/><path d="m9 3 4 1.5-3.5 9-4-1.5z"/><path d="M9.5 13.5 8 17.5"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.8 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.8-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="10" cy="7" r="1.2"/><circle cx="14.5" cy="7" r="1.2"/>',
    "sprout": '<path d="M12 21v-8.5"/><path d="M12 12.5C12 8.6 9.2 6 4.8 6c0 3.9 2.9 6.5 7.2 6.5z"/><path d="M12 10.5c0-3.7 2.7-6.5 7.2-6.5 0 3.9-2.8 6.5-7.2 6.5z"/><path d="M8 21h8"/>',
    "leaf": '<path d="M5 19c0-8 5-14 15-15-1 10-7 15-15 15z"/><path d="M5 19 13 11"/>',
    "egg": '<path d="M12 2.8c-3.9 0-7 6.1-7 10.6a7 7 0 0 0 14 0c0-4.5-3.1-10.6-7-10.6z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "settings": '<path d="M4 6.5h9M17 6.5h3M4 12h3M11 12h9M4 17.5h11M19 17.5h1"/><circle cx="15" cy="6.5" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="17.5" r="2"/>',
    "menu": '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-up": '<path d="m6 15 6-6 6 6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "expand": '<path d="M14.5 3.5h6v6M9.5 20.5h-6v-6M20.5 3.5l-7 7M3.5 20.5l7-7"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "galaxy": '<path d="M13.6 12.0 13.7 12.6 13.6 13.4 13.1 14.1 12.4 14.6 11.3 14.9 10.1 14.9 8.9 14.3 7.8 13.2 7.0 11.6 6.9 9.5 7.6 7.4 9.1 5.3 11.6 3.7 14.9 3.1"/><path d="M10.4 12.0 10.3 11.4 10.4 10.6 10.9 9.9 11.6 9.4 12.7 9.1 13.9 9.1 15.1 9.7 16.2 10.8 17.0 12.4 17.1 14.5 16.4 16.6 14.9 18.7 12.4 20.3 9.1 20.9"/><circle cx="12" cy="12" r="1.1"/><path d="M20.5 3.5h.01M3.6 20.2h.01"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5h.01"/>',
    "cart": '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M2.5 3.5h3l2.4 11.2a1.5 1.5 0 0 0 1.5 1.2h8.4a1.5 1.5 0 0 0 1.5-1.1L21 7.5H6.4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "trash": '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "box": '<path d="M2.5 4h19v4h-19z"/><path d="M4 8v11a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 19V8"/><path d="M10 12h4"/>',
    "tag": '<path d="M3 12.6V4.5A1.5 1.5 0 0 1 4.5 3h8.1a1.5 1.5 0 0 1 1.06.44l7.4 7.4a1.5 1.5 0 0 1 0 2.12l-8.1 8.1a1.5 1.5 0 0 1-2.12 0l-7.4-7.4A1.5 1.5 0 0 1 3 12.6z"/><circle cx="8" cy="8" r="1.6"/>',
}


def icon_svg(name: str, size: int = 20, cls: str = "icon") -> Markup:
    body = ICONS.get(name, ICONS["tool"])
    return Markup(
        f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )
