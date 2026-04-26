"""Service rendu d'email — substitue les variables {{var}} dans subject + body.

Phase 2.1. Pas de full Jinja2 (overkill) : substitution simple par regex.
Variables supportees :
- {{candidate.name}} {{candidate.email}} {{candidate.phone}}
- {{position.title}} {{position.seniority_level}}
- {{recruiter.name}} {{recruiter.email}}
- {{interview.scheduled_at}}
- {{tenant.name}}
- variables custom passees en extra_variables (ex: {{custom_link}})
"""
import re
from typing import Any

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _resolve_path(obj: Any, path: str) -> str | None:
    """Lookup objet par dot path (e.g. 'candidate.name')."""
    parts = path.split(".")
    current = obj
    for p in parts:
        if isinstance(current, dict):
            current = current.get(p)
        else:
            current = getattr(current, p, None)
        if current is None:
            return None
    return str(current)


def render_template(text: str, context: dict) -> tuple[str, list[str]]:
    """Substitue les {{var}} dans text. Retourne (rendered, list_of_vars_used).

    Une variable non resolue est laissee telle quelle (ex: {{unknown}}) pour
    permettre au user de detecter ses fautes de frappe.
    """
    used: list[str] = []

    def repl(match: re.Match) -> str:
        path = match.group(1)
        used.append(path)
        val = _resolve_path(context, path)
        if val is None:
            return match.group(0)  # Laisse le {{var}} si pas resolu
        return val

    rendered = VAR_RE.sub(repl, text)
    return rendered, used


def build_context(
    candidate: Any = None,
    position: Any = None,
    recruiter: Any = None,
    interview: Any = None,
    tenant: Any = None,
    extra: dict | None = None,
) -> dict:
    """Construit le contexte de rendu avec les entites courantes."""
    ctx: dict[str, Any] = {}
    if candidate is not None:
        ctx["candidate"] = candidate
    if position is not None:
        ctx["position"] = position
    if recruiter is not None:
        ctx["recruiter"] = recruiter
    if interview is not None:
        ctx["interview"] = interview
    if tenant is not None:
        ctx["tenant"] = tenant
    if extra:
        ctx.update(extra)
    return ctx
