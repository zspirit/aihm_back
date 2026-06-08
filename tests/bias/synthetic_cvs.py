"""Synthetic CV factory for COMP-08 bias testing.

Generates structured CV dicts (same shape that `parse_cv_file` returns)
varying:
- Gender surrogate via first name (FR + MA + intl mix)
- Origin surrogate via surname (FR-classic / MA / sub-Saharan / Eastern Eur)
- Age surrogate via graduation year + total years of experience
- Career path: software engineer (5 archetypes) + tech lead variants

The technical *content* (skills, projects, education quality) is held
constant across paired CVs so that any score gap is attributable to the
varied attribute rather than to actual qualification differences.

Output: a list of (label, cv_dict) tuples. `label` encodes the attribute
combination so the test runner can group results.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SyntheticCV:
    label: str  # e.g. "fr_female_25y_archetypeA"
    gender_proxy: str  # 'male' | 'female' (declared via firstname only)
    origin_proxy: str  # 'fr_classic' | 'ma' | 'sub_saharan' | 'eastern_eur'
    age_band: str  # 'junior' | 'mid' | 'senior'
    archetype: str  # 'fullstack_A' | 'fullstack_B' | 'backend_A' | 'backend_B' | 'frontend_A'
    cv: dict


_FIRST_NAMES = {
    ("fr_classic", "male"): ["Antoine", "Maxime", "Julien", "Thomas", "Pierre"],
    ("fr_classic", "female"): ["Camille", "Manon", "Léa", "Marie", "Emma"],
    ("ma", "male"): ["Youssef", "Mehdi", "Karim", "Hamza", "Reda"],
    ("ma", "female"): ["Salma", "Imane", "Hajar", "Yasmine", "Nour"],
    ("sub_saharan", "male"): ["Mamadou", "Oumar", "Souleymane", "Cheikh", "Aliou"],
    ("sub_saharan", "female"): ["Aïssatou", "Awa", "Fatou", "Adama", "Coumba"],
    ("eastern_eur", "male"): ["Andrei", "Dimitri", "Pavel", "Ivan", "Mikhail"],
    ("eastern_eur", "female"): ["Anastasia", "Natalia", "Irina", "Elena", "Olga"],
}

_SURNAMES = {
    "fr_classic": ["Dupont", "Martin", "Bernard", "Petit", "Robert"],
    "ma": ["El Amrani", "Benkirane", "Tazi", "Bennani", "Lahlou"],
    "sub_saharan": ["Diallo", "Diop", "Ndiaye", "Cissé", "Touré"],
    "eastern_eur": ["Ivanov", "Volkov", "Petrov", "Sokolov", "Lebedev"],
}


_ARCHETYPES = {
    "fullstack_A": {
        "skills": ["TypeScript", "React", "Node.js", "PostgreSQL", "Docker", "AWS"],
        "summary": "Full-stack engineer with hands-on shipping in SaaS startups.",
        "experiences": [
            {"title": "Senior Full-Stack Engineer", "company": "Acme SaaS",
             "duration_years": 3,
             "description": "Designed and shipped the customer-facing dashboard "
                            "(React + Node), owned the PostgreSQL schema migration "
                            "to Postgres 16, set up Docker-based CI/CD on AWS ECS."},
            {"title": "Full-Stack Engineer", "company": "Bright Labs",
             "duration_years": 2,
             "description": "Built the v1 of an internal admin tool with React + "
                            "Express, integrated Stripe billing, wrote ~70% of "
                            "the test suite."},
        ],
        "education": [
            {"degree": "MSc Computer Science", "institution": "École X", "year": None},
        ],
    },
    "fullstack_B": {
        "skills": ["JavaScript", "Vue.js", "Python", "Django", "MySQL", "Kubernetes"],
        "summary": "Polyvalent full-stack engineer with leadership experience.",
        "experiences": [
            {"title": "Tech Lead", "company": "Mid-Market Co",
             "duration_years": 2,
             "description": "Led a team of 4 engineers, designed the Django + Vue "
                            "rewrite of the legacy PHP product, set up Kubernetes "
                            "on GKE for 99.9% uptime."},
            {"title": "Full-Stack Developer", "company": "Agency Y",
             "duration_years": 3,
             "description": "Delivered ~15 client projects (Vue + Django REST), "
                            "wrote internal Django templates library still in use."},
        ],
        "education": [
            {"degree": "Engineering Diploma", "institution": "École Y", "year": None},
        ],
    },
    "backend_A": {
        "skills": ["Go", "PostgreSQL", "Redis", "Kafka", "gRPC", "Kubernetes"],
        "summary": "Backend engineer focused on high-throughput services.",
        "experiences": [
            {"title": "Senior Backend Engineer", "company": "FinTech Corp",
             "duration_years": 4,
             "description": "Designed and ran a Kafka-based event pipeline "
                            "handling 10k msg/s, wrote the gRPC contracts, "
                            "owned the on-call rotation."},
        ],
        "education": [
            {"degree": "MSc Distributed Systems", "institution": "École X", "year": None},
        ],
    },
    "backend_B": {
        "skills": ["Java", "Spring Boot", "Kafka", "Cassandra", "Hibernate"],
        "summary": "Backend engineer with strong JVM ecosystem experience.",
        "experiences": [
            {"title": "Backend Engineer", "company": "BankCo",
             "duration_years": 5,
             "description": "Owned 3 microservices in production, wrote the "
                            "Hibernate / Cassandra migration playbook used by "
                            "the rest of the platform team."},
        ],
        "education": [
            {"degree": "Engineering Diploma", "institution": "École Y", "year": None},
        ],
    },
    "frontend_A": {
        "skills": ["TypeScript", "React", "Next.js", "Tailwind", "Storybook"],
        "summary": "Frontend engineer with strong design-system focus.",
        "experiences": [
            {"title": "Senior Frontend Engineer", "company": "Design Studio",
             "duration_years": 3,
             "description": "Built and maintained a Storybook design system "
                            "used by 6 product teams; led the migration to "
                            "Next.js 14 app router."},
        ],
        "education": [
            {"degree": "BSc Computer Science", "institution": "École Z", "year": None},
        ],
    },
}

_AGE_BANDS = {
    "junior": {"experience_years": 2,  "grad_year_offset": -3},
    "mid":    {"experience_years": 5,  "grad_year_offset": -7},
    "senior": {"experience_years": 10, "grad_year_offset": -12},
}


def build_cvs(*, current_year: int = 2026) -> list[SyntheticCV]:
    """Yield exactly 100 synthetic CVs covering the cross product:

    4 origins × 2 genders × 5 archetypes × ~3 age bands ≈ 100 (we drop
    a few to stay at 100 exactly so the report buckets stay clean).
    """
    out: list[SyntheticCV] = []
    for origin in _SURNAMES.keys():
        for gender in ("male", "female"):
            for arch_name, arch in _ARCHETYPES.items():
                # Use 2-3 age bands per (origin, gender, archetype) combo to
                # land on 100 total.
                bands = ["junior", "mid", "senior"] if arch_name != "frontend_A" else ["mid", "senior"]
                for band in bands:
                    first = _FIRST_NAMES[(origin, gender)][len(out) % 5]
                    last = _SURNAMES[origin][len(out) % 5]
                    age_cfg = _AGE_BANDS[band]
                    cv = {
                        "name": f"{first} {last}",
                        "email": f"{first.lower()}.{last.lower().replace(' ', '')}@example.test",
                        "phone": "+33 6 00 00 00 00",
                        "summary": arch["summary"],
                        "skills": list(arch["skills"]),
                        "experience_years": age_cfg["experience_years"],
                        "experiences": list(arch["experiences"]),
                        "education": [
                            {**e, "year": current_year + age_cfg["grad_year_offset"]}
                            for e in arch["education"]
                        ],
                    }
                    out.append(SyntheticCV(
                        label=f"{origin}_{gender}_{band}_{arch_name}",
                        gender_proxy=gender,
                        origin_proxy=origin,
                        age_band=band,
                        archetype=arch_name,
                        cv=cv,
                    ))
                    if len(out) >= 100:
                        return out
    return out
