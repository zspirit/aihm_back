"""Jinja2 email template rendering."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


def render(template_name: str, **ctx) -> str:
    """Render an email template with the given context."""
    tpl = _env.get_template(template_name)
    return tpl.render(**ctx)
