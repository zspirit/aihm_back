"""Parsing CV → dossier de compétence (EPIC J) — GRATUIT, sans IA.

Extraction texte via PyMuPDF / python-docx, puis découpage heuristique en sections
(expériences, formations, certifications, langues, compétences) + regex de dates.
Déterministe, zéro coût, zéro dépendance externe supplémentaire. Le résultat est
pré-rempli dans le stepper où le consultant review/corrige/valide.
"""
from __future__ import annotations

import re
from io import BytesIO

import structlog

logger = structlog.get_logger(__name__)

_EMPTY = {"headline": "", "summary": "", "skills": [], "experiences": [], "education": [], "certifications": [], "languages": []}

# ── Sections (FR + EN) — détection tolérante : l'en-tête peut être suivi d'autre texte ─
_SECTIONS = [
    ("experiences", r"exp[ée]riences?|parcours\s+professionnel|work\s+experience|emplois?|carri[èe]re"),
    ("education", r"formations?|dipl[ôo]mes?|[ée]ducation|[ée]tudes|cursus|scolarit[ée]|education|parcours\s+(?:acad[ée]mique|scolaire)|acad[ée]mique|training"),
    ("certifications", r"certifications?|certificats?|certificates?|accr[ée]ditations?|habilitations?"),
    ("languages", r"langues?|languages?"),
    ("skills", r"comp[ée]tences?|skills|technologies?|stack|savoir[- ]faire|expertises?|outils|domaines|hard\s+skills"),
    # bornes ignorées en sortie — servent à arrêter l'absorption de la section précédente
    ("interests", r"centres?\s+d['’]?int[ée]r[êe]ts?|loisirs|hobbies|interests|activit[ée]s"),
    ("misc", r"informations?(?:\s+compl[ée]mentaires)?|divers|r[ée]f[ée]rences?|references?|projets?\s+personnels?|publications?"),
]
# match en début de ligne (l'en-tête peut être suivi d'une date ou de précisions)
_SECTION_RE = [(k, re.compile(rf"^\W*(?:{p})\b", re.I)) for k, p in _SECTIONS]


def _is_header(s: str) -> str | None:
    """Un en-tête de section : ligne courte (≤5 mots), sans date ni séparateur d'entrée,
    commençant par un mot-clé de section."""
    if not s or len(s) > 55:
        return None
    if _RANGE_RE.search(s) or _SEP_RE.search(s):
        return None  # ligne d'entrée (poste — société 2024→2025), pas un en-tête
    if len(s.split()) > 5:
        return None
    for key, rx in _SECTION_RE:
        if rx.match(s):
            return key
    return None

_DATE = r"(?:\d{1,2}[/.]\d{4}|[A-Za-zéûàùî]{3,10}\.?\s?\d{4}|\d{4}|pr[ée]sent|aujourd['’]?hui|en\s+cours|now|…|\.\.\.)"
_RANGE_RE = re.compile(rf"({_DATE})\s*(?:→|-+>|–|—|-|à|au|to|jusqu['’]?)\s*({_DATE})", re.I)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_SEP_RE = re.compile(r"\s+(?:[•·@|]|[-–—]|chez|at)\s+", re.I)
_LEVEL_RE = re.compile(r"[(:\-–]\s*([A-Za-zÀ-ÿ0-9 .+]{2,20})\)?\s*$")
_BULLET = r"[,;•·▪◦•|\n]|\s{2,}|\t"
_ROLE_RE = re.compile(r"dev|lead|manager|consultant|engineer|ing[ée]nieur|architecte?|analyst|designer|\bsre\b|\bops\b|chef|directeur|expert|sp[ée]cialiste", re.I)
_DEGREE_KW = re.compile(r"master|licence|doctorat|baccalaur|bac|bts|b\.?t\.?s|dut|d\.?u\.?t|mba|ing[ée]nieur|dipl[ôo]me|bachelor|ph\.?\s?d|ma[îi]trise|deug|cap|pr[ée]pa|mast[èe]re|msc|bsc|certificat|dess|dea|dec|brevet", re.I)
_SCHOOL_KW = re.compile(r"universit|[ée]cole|institut|university|college|lyc[ée]e|cnam|insa|ens|enseeiht|hec|essec|polytechni|facult|epitech|epita|iut|business\s+school|sup[ée]rieure?|dauphine|sorbonne|centrale|mines|ponts|gobelins|esc|iae", re.I)


_PUA_RE = re.compile(r"[-]")  # glyphes de police prives (puces Wingdings -> box)
_ZAP_RE = re.compile(r"[￼�​-\u200F]")  # objet/remplacement + largeur nulle


def _clean_text(t: str) -> str:
    t = _PUA_RE.sub(" • ", t)      # puces parasites → vraie puce (affichable + sert au split)
    t = _ZAP_RE.sub("", t)
    t = t.replace(" ", " ")   # espace insecable -> espace normal
    t = re.sub(r"[ \t]{3,}", "  ", t)  # garde le signal \s{2,} sans gaps énormes
    return t


def extract_cv_text(content: bytes, filename: str) -> str:
    name = (filename or "").lower()
    text = ""
    try:
        if name.endswith(".pdf"):
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
        elif name.endswith((".docx", ".doc")):
            from docx import Document
            d = Document(BytesIO(content))
            text = "\n".join(p.text for p in d.paragraphs)
        else:
            text = content.decode("utf-8", errors="ignore")
    except Exception:
        logger.warning("cv_text_extract_failed", filename=filename)
        text = content.decode("utf-8", errors="ignore")
    return _clean_text(text)


def _split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"_header": []}
    current = "_header"
    for raw in text.splitlines():
        matched = _is_header(raw.strip())
        if matched:
            current = matched
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(raw)
    return sections


def _list_items(block: list[str], maxlen: int = 45) -> list[str]:
    raw = re.split(_BULLET, "\n".join(block))
    out, seen = [], set()
    for x in raw:
        v = x.strip(" -\t·•").strip()
        if v and 1 < len(v) <= maxlen and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


_LANG_NOISE = {"et", "and", "ou", "langue", "langues", "language", "languages", "niveau", "level", "courant", "natif", "native", "maternelle", "bilingue", "scolaire", "professionnel", "professionnelle", "intermédiaire", "débutant", "lu", "écrit", "parlé"}


def _languages(block: list[str]) -> list[dict]:
    text = " | ".join(l.strip() for l in block if l.strip())
    if not text:
        return []
    langs: list[dict] = []
    seen: set[str] = set()

    def _add(name: str, level: str):
        nm = name.strip(" .,;:-()'’").strip()
        if nm and 2 <= len(nm) <= 22 and nm.lower() not in _LANG_NOISE and nm.lower() not in seen:
            seen.add(nm.lower())
            langs.append({"name": nm, "level": (level or "").strip(" .,;:-()'’")})

    used = text
    # 1) "Nom (niveau)"  ex: Français (Bilingue)
    for m in re.finditer(r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’ -]{2,18}?)\s*\(([^)]{2,20})\)", text):
        _add(m.group(1), m.group(2))
        used = used.replace(m.group(0), " | ")
    # 2) "Nom : niveau"  ex: Anglais : courant
    for m in re.finditer(r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’ -]{2,18}?)\s*:\s*([A-Za-zÀ-ÿ][\wÀ-ÿ +/]{1,18})", used):
        _add(m.group(1), m.group(2))
        used = used.replace(m.group(0), " | ")
    # 3) noms nus restants  ex: Arabe, Espagnol
    for tok in re.split(r"[,;/•·|]|\s{2,}|\s(?=[A-ZÀ-Ÿ])", used):
        _add(tok, "")
    return langs[:12]


def _entries(block: list[str]) -> list[list[str]]:
    """Découpe un bloc en entrées : par lignes vides, sinon par lignes contenant une date."""
    text = "\n".join(block).strip()
    if not text:
        return []
    chunks = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
    if len(chunks) > 1:
        return [c.splitlines() for c in chunks]
    # pas de séparation par lignes vides → on coupe avant chaque ligne datée
    entries, cur = [], []
    for line in text.splitlines():
        has_date = bool(_RANGE_RE.search(line) or _YEAR_RE.search(line))
        if has_date and cur:
            entries.append(cur)
            cur = [line]
        else:
            cur.append(line)
    if cur:
        entries.append(cur)
    return entries


def _parse_experience(lines: list[str]) -> dict:
    joined = " ".join(l.strip() for l in lines if l.strip())
    period = ""
    rng = _RANGE_RE.search(joined)
    if rng:
        period = rng.group(0)
    elif _YEAR_RE.search(joined):
        period = _YEAR_RE.search(joined).group(0)
    # 1ère ligne = titre (+ société si séparateur)
    head = next((l.strip() for l in lines if l.strip()), "")
    head = _RANGE_RE.sub("", head).strip(" -–—|·•")
    title, company = head, ""
    sep = _SEP_RE.split(head, maxsplit=1)
    if len(sep) == 2:
        title, company = sep[0].strip(), sep[1].strip()
    elif len(lines) > 1:
        cand = lines[1].strip()
        if cand and not _RANGE_RE.search(cand) and len(cand) < 60:
            company = _RANGE_RE.sub("", cand).strip()
    body = [l.strip() for l in lines[1:] if l.strip() and l.strip() != company and not _RANGE_RE.fullmatch(l.strip())]
    return {"title": title[:120], "company": company[:120], "period": period[:40], "description": " ".join(body)[:600]}


def _parse_education(lines: list[str]) -> dict:
    """Detection generique par mots-cles (independante de l'ordre des lignes)."""
    parts: list[str] = []
    for l in lines:
        for seg in _SEP_RE.split(l):
            seg = seg.strip()
            if seg:
                parts.append(seg)
    joined = " ".join(parts)
    ym = _YEAR_RE.search(joined)
    year = ym.group(0) if ym else ""
    clean = [c for c in (_YEAR_RE.sub("", x).strip(" -–—|·•,") for x in parts) if c]
    if not clean:
        return {"degree": "", "school": "", "year": year}
    degree = next((c for c in clean if _DEGREE_KW.search(c)), clean[0])
    school = next((c for c in clean if _SCHOOL_KW.search(c) and c != degree), "")
    if not school:
        school = next((c for c in clean if c != degree), "")
    return {"degree": degree[:120], "school": school[:120], "year": year}


def parse_cv_to_profile(text: str) -> dict:
    if not text or not text.strip():
        return dict(_EMPTY)
    try:
        sec = _split_sections(text)
        skills = _list_items(sec.get("skills", []))
        languages = _languages(sec.get("languages", []))
        experiences = [_parse_experience(e) for e in _entries(sec.get("experiences", []))][:12]
        experiences = [x for x in experiences if x["title"] or x["company"] or x["description"]]
        education = [_parse_education(e) for e in _entries(sec.get("education", []))][:8]
        education = [x for x in education if x["degree"] or x["school"] or x["year"]]
        certifications = []
        for it in _list_items(sec.get("certifications", []), maxlen=120):
            year = _YEAR_RE.search(it).group(0) if _YEAR_RE.search(it) else ""
            certifications.append({"name": _YEAR_RE.sub("", it).strip(" -–—|·•"), "issuer": "", "year": year})
        # en-tête : headline (ligne de rôle) + résumé (paragraphe long)
        header = [l.strip() for l in sec.get("_header", []) if l.strip() and "@" not in l and not re.search(r"\d{2}[.\s]\d{2}[.\s]\d{2}", l)]
        headline = next((l for l in header if 4 < len(l) <= 60 and _ROLE_RE.search(l)), "")
        summary = next((l for l in header if len(l) > 80), "")
        if not summary:
            summary = " ".join(l for l in header if l != headline and len(l) > 40)[:600]
        return {
            "headline": headline, "summary": summary, "skills": skills,
            "experiences": experiences, "education": education,
            "certifications": certifications, "languages": languages,
        }
    except Exception:
        logger.warning("cv_parse_heuristic_failed")
        return dict(_EMPTY)
