"""Visual layer: SAP Fiori Horizon look on NiceGUI.

Only styling and layout live here: design tokens as CSS variables, the shell
bar, side navigation and reusable widgets (KPI tile, tag chip, status badge).
"""

from __future__ import annotations

from pathlib import Path

from contextlib import contextmanager
from typing import Iterator
from urllib.parse import quote

from nicegui import ui

from atlas import __version__

# --- Horizon design tokens ------------------------------------------------------------
CSS = """
:root {
  --sapBrand: #0070F2;
  --sapBrandDark: #0040B0;
  --sapText: #1D2D3E;
  --sapText2: #556B82;
  --sapBg: #F5F6F7;
  --sapTile: #FFFFFF;
  --sapBorder: #E5E5E5;
  --sapShellBorder: #D9D9D9;
  --sapPositive: #256F3A;
  --sapCritical: #E76500;
  --sapNegative: #AA0808;
  --sapNeutral: #5B738B;
  --sapInfo: #0070F2;
  --sapRadius: 0.75rem;
  --sapShadow: 0 0 0.125rem rgba(34,54,73,.12), 0 .125rem .25rem rgba(34,54,73,.12);
}
html, body, .q-page { background: var(--sapBg) !important; color: var(--sapText); }
body, .q-field, .q-btn, .q-table { font-family: "72", "72full", -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
.shell { background: var(--sapTile); border-bottom: 1px solid var(--sapShellBorder); height: 3.25rem; }
.shell .brand { display:flex; align-items:center; gap:.6rem; font-weight: 700; font-size: 1.2rem; letter-spacing: -0.01em; color: var(--sapText); }
.shell .brand .name { color: var(--sapBrandDark); font-size: 1.25rem; }
.shell .brand .name b { color: var(--sapBrand); font-weight: 800; }
.shell .brand .tag { display:none; }
.shell .tagline { color: var(--sapText2); font-size: .85rem; border-left: 1px solid var(--sapShellBorder); padding-left: .8rem; }
.shell .by { color: var(--sapText2); font-size: .75rem; }
.nav .product { padding: .25rem .75rem 1rem; color: var(--sapText2); font-size: .72rem; }
.nav { background: var(--sapTile); border-right: 1px solid var(--sapShellBorder); }
.nav-item { border-radius: .5rem; padding: .5rem .75rem; color: var(--sapText); cursor: pointer; display:flex; gap:.6rem; align-items:center; }
.nav-item:hover { background: #EAF2FD; }
.nav-item.active { background: #EAF2FD; color: var(--sapBrandDark); font-weight: 600; }
.tile { background: var(--sapTile); border-radius: var(--sapRadius); box-shadow: var(--sapShadow); padding: 1rem 1.25rem; }
.kpi-label { color: var(--sapText2); font-size: .8rem; text-transform: none; }
.kpi-value { font-size: 2rem; font-weight: 300; line-height: 1.1; color: var(--sapText); }
.kpi-sub { color: var(--sapText2); font-size: .75rem; }
.page-title { font-size: 1.5rem; font-weight: 400; color: var(--sapText); margin: 0; }
.page-sub { color: var(--sapText2); font-size: .9rem; }
.section-title { font-size: 1rem; font-weight: 600; color: var(--sapText); }
.tag { display:inline-block; border-radius: .5rem; padding: .05rem .55rem; font-size: .75rem; background:#EAF2FD; color: var(--sapBrandDark); margin: .1rem .25rem .1rem 0; border:1px solid #C2DCFB; }
.tag.neutral { background:#F5F6F7; color: var(--sapText2); border-color: var(--sapBorder); }
.badge { display:inline-block; border-radius: .5rem; padding: .05rem .5rem; font-size: .72rem; font-weight:600; }
.badge.ai { background:#E3F5E9; color: var(--sapPositive); }
.badge.offline { background:#F5F6F7; color: var(--sapText2); border:1px solid var(--sapBorder); }
.badge.human { background:#EAF2FD; color: var(--sapBrandDark); }
.badge.strong { background:#E3F5E9; color: var(--sapPositive); }
.badge.good { background:#FFF3E0; color: var(--sapCritical); }
.badge.weak { background:#F5F6F7; color: var(--sapText2); }
.badge.done { background:#E3F5E9; color: var(--sapPositive); }
.badge.failed { background:#FDE4E4; color: var(--sapNegative); }
.badge.running { background:#EAF2FD; color: var(--sapBrandDark); }
.badge.skipped { background:#F5F6F7; color: var(--sapText2); }
.result { background: var(--sapTile); border-radius: var(--sapRadius); box-shadow: var(--sapShadow); padding: .9rem 1.1rem; border-left: 4px solid var(--sapBrand); }
.result.weak { border-left-color: var(--sapBorder); }
.obj-name { font-family: "Cascadia Mono", Consolas, "Courier New", monospace; font-weight: 700; color: var(--sapBrandDark); font-size: 1rem; text-decoration: none; }
.obj-name:hover { text-decoration: underline; }
.meta { color: var(--sapText2); font-size: .8rem; }
.desc { color: var(--sapText); line-height: 1.5; font-size: .92rem; }
.mono { font-family: "Cascadia Mono", Consolas, monospace; font-size: .85rem; }
.hit { color: var(--sapText2); font-size: .8rem; margin-left: .25rem; }
.hit b { color: var(--sapText); font-weight: 600; font-family: Consolas, monospace; }
.q-table th { color: var(--sapText2); font-weight: 600; }
.src .hl { background: #FFF3C4; display: inline-block; width: 100%; }
.answer { line-height: 1.55; font-size: .95rem; }
.answer p { margin: .4rem 0; }
.answer ul { margin: .3rem 0 .3rem 1.2rem; }
.answer code { background: #F2F4F6; padding: 0 .25rem; border-radius: .25rem; font-size: .85rem; }
.cite { color: var(--sapBrand); font-family: ui-monospace, monospace; font-size: .85rem; text-decoration: none; }
.cite:hover { text-decoration: underline; }
.q-table tbody tr:hover { background: #EAF2FD !important; cursor: pointer; }
.q-field--outlined .q-field__control { border-radius: .5rem; background: var(--sapTile); }
.q-btn { border-radius: .5rem; text-transform: none; font-weight: 600; }
.example { cursor:pointer; }
.example:hover { background:#DCEBFB; }
pre.src { background:#1D2D3E; color:#E8EEF5; border-radius: var(--sapRadius); padding: 1rem; font-family: "Cascadia Mono", Consolas, monospace; font-size:.8rem; line-height:1.4; overflow:auto; max-height: 70vh; }
pre.src.wrap { white-space: pre-wrap; word-break: break-word; }
.by-company { display:inline-flex; align-items:center; gap:.4rem; }
.company-mark { font-weight:800; font-size:1.05rem; letter-spacing:.02em; line-height:1; font-family: "72", "Segoe UI", Arial, sans-serif; }
.company-mark .cm-a { color:#1F8FD6; }
.company-mark .cm-b { color:#E02A2A; }
pre.src .ln { color:#7A8FA6; display:inline-block; width:3.2rem; user-select:none; }
"""

import os

# --- product branding (override with env ATLAS_PRODUCT_NAME / ATLAS_PRODUCT_TAGLINE) -------------
PRODUCT_NAME = os.environ.get("ATLAS_PRODUCT_NAME", "ABAP Beacon")
PRODUCT_TAGLINE = os.environ.get("ATLAS_PRODUCT_TAGLINE", "Custom Code Intelligence for SAP")
PRODUCT_BY = os.environ.get("ATLAS_PRODUCT_BY", "by InfraBeat")

LOGO_SVG = (
    '<svg width="30" height="30" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-label="ABAP Beacon">'
    '<defs><linearGradient id="bg" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#0040B0"/><stop offset="1" stop-color="#1B90FF"/></linearGradient></defs>'
    '<rect x="2" y="2" width="60" height="60" rx="14" fill="url(#bg)"/>'
    # light beams
    '<path d="M36 17 L58 9" stroke="#FFD54F" stroke-width="3" stroke-linecap="round" opacity=".9"/>'
    '<path d="M37 22 L60 22" stroke="#FFD54F" stroke-width="3" stroke-linecap="round" opacity=".9"/>'
    '<path d="M36 27 L58 35" stroke="#FFD54F" stroke-width="3" stroke-linecap="round" opacity=".9"/>'
    # lantern + tower
    '<circle cx="30" cy="22" r="5" fill="#FFB300"/>'
    '<path d="M25 30 H35 L38 52 H22 Z" fill="#fff"/>'
    '<rect x="18" y="52" width="24" height="4" rx="2" fill="#fff" opacity=".85"/>'
    '</svg>'
)
FAVICON_SVG = LOGO_SVG.replace('width="30" height="30"', 'width="64" height="64"')

ASSETS_DIR = Path(__file__).parent / "assets"
_COMPANY_LOGO_FILES = ("infrabeat_logo.svg", "infrabeat_logo.png", "company_logo.svg", "company_logo.png")


def company_logo_html(height: int = 26) -> str:
    """The company logo in the shell bar. Drop `infrabeat_logo.svg` or `.png` into atlas/ui/assets to
    show the real logo; until then a clean wordmark is used."""
    for name in _COMPANY_LOGO_FILES:
        if (ASSETS_DIR / name).exists():
            return f'<img src="/assets/{name}" alt="{escape(PRODUCT_BY)}" style="height:{height}px;width:auto;display:block">'
    company = PRODUCT_BY.replace("by ", "").strip()
    return (f'<span class="company-mark" title="{escape(company)}"><span class="cm-a">{escape(company[:5])}</span>'
            f'<span class="cm-b">{escape(company[5:])}</span></span>')

NAV = [
    ("Overview", "dashboard", "/"),
    ("Executive view", "insights", "/value"),
    ("Discover", "search", "/discover"),
    ("Ask the codebase", "forum", "/ask"),
    ("Assessments", "fact_check", "/assessments"),
    ("FSD analysis", "rule", "/fsd"),
    ("Dependency map", "hub", "/dependencies"),
    ("Inventory", "inventory_2", "/inventory"),
    ("Jobs & Pipeline", "settings_suggest", "/jobs"),
]
SETTINGS_NAV = [
    ("Workspaces", "workspaces", "/workspaces"),
    ("AI provider", "smart_toy", "/ai"),
    ("Guardrails", "shield", "/guardrails"),
]
ROADMAP_NAV = ["Documents"]


def brand_html() -> str:
    """'ABAP Beacon' with the second word emphasised; other names render plainly."""
    parts = PRODUCT_NAME.split(" ", 1)
    if len(parts) == 2:
        return f"{escape(parts[0])} <b>{escape(parts[1])}</b>"
    return escape(PRODUCT_NAME)


def apply_theme() -> None:
    ui.add_head_html(f"<style>{CSS}</style>")
    ui.colors(primary="#0070F2", secondary="#5B738B", accent="#0040B0", positive="#256F3A", negative="#AA0808", warning="#E76500", info="#0070F2")


@contextmanager
def frame(active: str, system_label: str = "") -> Iterator[ui.column]:
    """Shell bar + side navigation around a page body."""
    apply_theme()
    ui.query(".nicegui-content").classes("p-0")

    with ui.header().classes("shell items-center px-4 gap-4").style("box-shadow:none"):
        ui.html(f'<a class="brand" href="/" style="text-decoration:none">{LOGO_SVG}<span class="name">{brand_html()}</span></a>')
        ui.html(f'<span class="tagline">{escape(PRODUCT_TAGLINE)}</span>')
        ui.space()
        search = ui.input(placeholder="Describe what you need... e.g. report that ages vendor open items").props(
            "outlined dense clearable"
        ).classes("w-[28rem] max-w-[40vw]")
        search.on("keydown.enter", lambda: ui.navigate.to(f"/discover?q={quote(search.value)}") if search.value else None)
        try:
            from atlas.ui import data as _d
            _ws = _d.active_workspace()
            ui.link(f"{_ws.name}" + (" · strict" if _ws.strict else ""), "/workspaces").classes("tag").style("text-decoration:none;font-weight:600" + (";background:#FFF3E0;color:#B35A00" if _ws.strict else ""))
        except Exception:      # noqa: BLE001
            pass
        if system_label:
            ui.html(f'<span class="tag">{system_label}</span>')
        ui.html(f'<span class="by-company"><span class="by">by</span>{company_logo_html()}</span>')

    with ui.left_drawer(value=True, fixed=True).classes("nav p-3").props("width=230 bordered"):
        for label, icon, path in NAV:
            cls = "nav-item active" if active == label else "nav-item"
            with ui.element("div").classes(cls).on("click", lambda p=path: ui.navigate.to(p)):
                ui.icon(icon, size="20px")
                ui.label(label)
        ui.separator().classes("my-3")
        ui.label("Settings").classes("meta px-3")
        for label, icon, path in SETTINGS_NAV:
            cls = "nav-item active" if active == label else "nav-item"
            with ui.element("div").classes(cls).on("click", lambda p=path: ui.navigate.to(p)):
                ui.icon(icon, size="20px")
                ui.label(label)
        ui.space()
        ui.html(f'<div class="product">{escape(PRODUCT_NAME)} - {escape(PRODUCT_TAGLINE)}<br><span style="display:inline-flex;align-items:center;gap:.35rem;margin-top:.25rem">by {company_logo_html(18)}</span></div>')

    with ui.column().classes("w-full p-6 gap-5 max-w-[1400px]") as body:
        yield body


# --- widgets ---------------------------------------------------------------------------

def kpi(label: str, value: str | int, sub: str = "", icon: str = "") -> None:
    with ui.element("div").classes("tile min-w-[11rem] flex-1"):
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            ui.label(label).classes("kpi-label")
            if icon:
                ui.icon(icon, size="20px").style("color: var(--sapText2)")
        text = str(value)
        size = "2rem" if len(text) <= 10 else "1.5rem" if len(text) <= 16 else "1.25rem" if len(text) <= 24 else "1.1rem"     # long values shrink instead of wrapping
        ui.label(text).classes("kpi-value").style(f"font-size:{size}")
        if sub:
            ui.label(sub).classes("kpi-sub")


def tags_html(tags: list[str], limit: int = 12, neutral_after: int = 3) -> str:
    out = []
    for i, t in enumerate(tags[:limit]):
        cls = "tag" if i < neutral_after else "tag neutral"
        out.append(f'<span class="{cls}">{escape(t)}</span>')
    if len(tags) > limit:
        out.append(f'<span class="tag neutral">+{len(tags) - limit}</span>')
    return "".join(out)


SEVERITY_COLOURS = {"high": ("#FFEAEA", "#AA0808"), "medium": ("#FFF3E0", "#B35A00"), "low": ("#E6F2FF", "#0A6ED1"), "info": ("#F0F1F3", "#556B82")}


def severity_badge(sev: str) -> str:
    bg, fg = SEVERITY_COLOURS.get(sev, SEVERITY_COLOURS["info"])
    return f'<span class="badge" style="background:{bg};color:{fg};border:1px solid {fg}22">{escape(sev)}</span>'


def badge(text: str, kind: str) -> str:
    return f'<span class="badge {kind}">{escape(text)}</span>'


def escape(text: str) -> str:
    import html

    return html.escape(str(text))


def source_block(text: str, max_lines: int = 400, highlight: set[int] | None = None, start: int = 1) -> str:
    """Numbered source; `highlight` marks lines (e.g. findings); `start` shows a window beginning there."""
    lines = text.splitlines()
    first = max(1, start)
    shown = lines[first - 1: first - 1 + max_lines]
    highlight = highlight or set()
    body = "\n".join(
        f'<span class="ln">{i:>4}</span>{"<span class=hl>" if i in highlight else ""}{escape(line)}{"</span>" if i in highlight else ""}'
        for i, line in enumerate(shown, start=first)
    )
    if first > 1:
        body = f'<span class="ln"></span>... {first - 1:,} lines above\n' + body
    remaining = len(lines) - (first - 1 + len(shown))
    if remaining > 0:
        body += f'\n<span class="ln"></span>... {remaining:,} more lines - use Download.'
    return f'<pre class="src">{body}</pre>'
