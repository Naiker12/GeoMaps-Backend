"""Decorative borders for generated cartography figures."""

from __future__ import annotations

from typing import Any


def draw_border(fig: Any, border_style: str) -> None:
    if border_style == "none":
        return

    from matplotlib.patches import Rectangle

    if border_style == "simple":
        rectangles = [
            Rectangle((0.012, 0.012), 0.976, 0.976, transform=fig.transFigure, fill=False, linewidth=1.1, edgecolor="#334155"),
        ]
    elif border_style == "transparent":
        rectangles = [
            Rectangle((0.014, 0.014), 0.972, 0.972, transform=fig.transFigure, fill=False, linewidth=1.25, edgecolor="#0F172A", alpha=0.45),
        ]
    elif border_style == "fancy":
        rectangles = [
            Rectangle((0.010, 0.010), 0.980, 0.980, transform=fig.transFigure, fill=False, linewidth=1.25, edgecolor="#0F172A"),
            Rectangle((0.022, 0.022), 0.956, 0.956, transform=fig.transFigure, fill=False, linewidth=0.55, edgecolor="#64748B"),
        ]
    else:
        return

    for rectangle in rectangles:
        rectangle.set_zorder(1000)
        fig.add_artist(rectangle)
