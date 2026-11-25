"""Design tokens: the one place the palette is defined. Page CSS, component CSS and the HTML embeds all read it."""
PALETTE = {
    "ink": "#1E0525", "plum": "#32073E", "violet": "#5B2A86", "lilac": "#8C5FB9", "peach": "#FFB49D",
    "pink": "#FFCDFF", "rose": "#C0446A", "amber": "#E0855F", "sand": "#ECE5D8", "line": "#F0EAE2",
    "cream": "#FDF8F3", "blush": "#FAE8E8", "muted": "#8E8292", "soft": "#6E5C76", "tag": "#FFE3D8",
}


def css_vars(selector: str = ":root") -> str:
    return selector + "{" + ";".join(f"--{k}:{v}" for k, v in PALETTE.items()) + "}"
