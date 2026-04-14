"""Service d'anonymisation des donnees CV d'un candidat.

Supprime les informations personnelles identifiantes et anonymise
les noms d'entreprises et d'ecoles.
"""

import re

import structlog

logger = structlog.get_logger()


def anonymize_candidate_data(candidate_id: str, cv_parsed_data: dict) -> dict:
    """Retourne une version anonymisee des donnees CV.

    Supprime : nom, email, telephone, adresse, photo, date de naissance, liens reseaux sociaux.
    Garde : competences, experience (entreprises anonymisees), formation (ecoles anonymisees), langues.

    Args:
        candidate_id: UUID du candidat (string)
        cv_parsed_data: Donnees CV parsees (dict)

    Returns:
        dict avec les donnees anonymisees
    """
    if not cv_parsed_data:
        return {
            "anonymous_id": _make_anonymous_id(candidate_id),
            "skills": [],
            "experiences": [],
            "education": [],
            "languages": [],
            "experience_years": None,
            "summary": None,
        }

    # Extract candidate name for scrubbing
    candidate_name = cv_parsed_data.get("name") or None

    # Build company mapping
    companies = _extract_unique_values(cv_parsed_data, "experiences", "company")
    company_map = {name: f"Entreprise {chr(65 + i)}" for i, name in enumerate(companies)}

    # Build school mapping
    schools = _extract_unique_values(cv_parsed_data, "education", "institution")
    school_map = {name: f"Ecole {chr(88 + i) if i < 3 else chr(65 + i - 3)}" for i, name in enumerate(schools)}

    # Anonymize experiences
    experiences = []
    for exp in cv_parsed_data.get("experiences", cv_parsed_data.get("experience", [])):
        anon_exp = {
            "title": exp.get("title", ""),
            "company": company_map.get(exp.get("company", ""), "Entreprise anonyme"),
            "duration": exp.get("duration", ""),
            "duration_months": exp.get("duration_months"),
            "responsibilities": exp.get("responsibilities", []),
            "key_achievements": exp.get("key_achievements", []),
            "description": exp.get("description", ""),
        }
        # Scrub company/school/candidate names from free-text fields
        for field in ("responsibilities", "key_achievements"):
            anon_exp[field] = [
                _scrub_names(text, company_map, school_map, candidate_name)
                for text in (anon_exp.get(field) or [])
            ]
        # Scrub description field (job description text)
        if anon_exp.get("description"):
            anon_exp["description"] = _scrub_names(
                anon_exp["description"], company_map, school_map, candidate_name
            )
        experiences.append(anon_exp)

    # Anonymize education
    education = []
    for edu in cv_parsed_data.get("education", []):
        anon_edu = {
            "degree": edu.get("degree", ""),
            "field": edu.get("field", ""),
            "institution": school_map.get(edu.get("institution", ""), "Ecole anonyme"),
            "year": edu.get("year"),
        }
        education.append(anon_edu)

    # Anonymize summary — remove personal references
    summary = cv_parsed_data.get("summary", "")
    if summary:
        summary = _scrub_names(summary, company_map, school_map, candidate_name)
        summary = _remove_personal_info_from_text(summary)

    return {
        "anonymous_id": _make_anonymous_id(candidate_id),
        "skills": cv_parsed_data.get("skills", []),
        "experiences": experiences,
        "education": education,
        "languages": cv_parsed_data.get("languages", []),
        "experience_years": cv_parsed_data.get("experience_years"),
        "summary": summary or None,
    }


def _make_anonymous_id(candidate_id: str) -> str:
    """Genere un identifiant anonyme a partir des 4 derniers caracteres de l'UUID."""
    clean_id = candidate_id.replace("-", "")
    return f"Candidat #{clean_id[-4:].upper()}"


def _extract_unique_values(data: dict, list_key: str, field_key: str) -> list[str]:
    """Extrait les valeurs uniques d'un champ dans une liste de dicts, en preservant l'ordre."""
    seen = set()
    result = []
    for item in data.get(list_key, data.get("experience", [])) if list_key == "experiences" else data.get(list_key, []):
        value = item.get(field_key, "")
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _scrub_names(
    text: str, company_map: dict, school_map: dict, candidate_name: str | None = None
) -> str:
    """Remplace les noms d'entreprises, d'ecoles et du candidat dans un texte."""
    for original, replacement in company_map.items():
        if original:
            text = text.replace(original, replacement)
    for original, replacement in school_map.items():
        if original:
            text = text.replace(original, replacement)
    if candidate_name:
        text = _scrub_candidate_name(text, candidate_name)
    return text


def _scrub_candidate_name(text: str, full_name: str) -> str:
    """Supprime le nom du candidat et ses variantes du texte.

    Gere le nom complet, prenom, nom de famille, et les titres francais (M., Mme, etc.).
    Ne scrub pas les mots de 3 caracteres ou moins pour eviter les faux positifs.
    """
    parts = full_name.strip().split()
    if not parts:
        return text

    # Full name first (most specific)
    text = re.sub(r'\b' + re.escape(full_name.strip()) + r'\b', '[candidat]', text, flags=re.IGNORECASE)

    # French title variations with name parts
    title_prefixes = ["M.", "Mr.", "Mme", "Mlle", "Dr.", "Pr."]
    for part in parts:
        if len(part) <= 3:
            continue
        for title in title_prefixes:
            pattern = re.escape(title) + r'\s+' + re.escape(part)
            text = re.sub(pattern, '[candidat]', text, flags=re.IGNORECASE)

    # Individual name parts (only if > 3 chars)
    for part in parts:
        if len(part) <= 3:
            continue
        text = re.sub(r'\b' + re.escape(part) + r'\b', '[candidat]', text, flags=re.IGNORECASE)

    return text


def _remove_personal_info_from_text(text: str) -> str:
    """Supprime les patterns d'informations personnelles d'un texte."""
    # Remove email patterns
    text = re.sub(r'\S+@\S+\.\S+', '[email]', text)
    # Remove phone patterns
    text = re.sub(r'(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{0,4}', '', text)
    # Remove URLs (social media links etc.)
    text = re.sub(r'https?://\S+', '[lien]', text)
    text = re.sub(r'www\.\S+', '[lien]', text)
    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text
