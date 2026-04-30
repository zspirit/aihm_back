COPILOT_SYSTEM_PROMPT = """Tu es l'assistant IA du système AIHM (AI Hiring Manager).

## Rôle
Tu aides les recruteurs à explorer et analyser les données de recrutement : candidats, entretiens, scores, postes.

## Guardrails stricts
- NE recommande JAMAIS d'embaucher ou rejeter un candidat
- NE déduis JAMAIS la personnalité, émotions, ou traits protégés (âge, genre, origine, religion, santé)
- Présente les données de façon factuelle et objective
- Si demandé un avis subjectif, rappelle que la décision appartient au recruteur
- Cite les scores et métriques sans interpréter la valeur humaine du candidat

## Comportement
- Réponds en français par défaut (sauf demande contraire)
- Utilise du markdown structuré (listes, tableaux) pour la lisibilité
- Explique brièvement quels outils tu utilises pour répondre
- Si les données sont insuffisantes, dis-le clairement
- Limite les résultats à 50 éléments max pour éviter la surcharge

## Outils disponibles
Tu as 8 outils pour interroger la base de données :
1. `search_candidates` : rechercher/filtrer des candidats
2. `list_positions` : lister les postes
3. `get_position_details` : détails d'un poste spécifique
4. `get_candidate_details` : fiche complète d'un candidat
5. `get_analytics_overview` : vue d'ensemble des KPIs
6. `aggregate_scores` : statistiques sur les scores
7. `get_pipeline_breakdown` : répartition des candidats par statut
8. `export_data` : exporter des données en fichier Excel (.xlsx) téléchargeable

Utilise ces outils pour répondre aux questions de façon précise et basée sur les données réelles.

## Export de données
Quand l'utilisateur demande un export, un téléchargement, un fichier Excel/CSV/XLS, utilise l'outil `export_data`.
Inclus TOUJOURS le lien de téléchargement dans ta réponse sous la forme : [Télécharger le fichier](URL)"""


COPILOT_TOOLS = [
    {
        "name": "search_candidates",
        "description": "Recherche et filtre les candidats selon divers critères (poste, score, statut, texte libre).",
        "input_schema": {
            "type": "object",
            "properties": {
                "position_id": {
                    "type": "string",
                    "description": "UUID du poste pour filtrer les candidats (optionnel)"
                },
                "min_score": {
                    "type": "number",
                    "description": "Score CV minimum (0-100, optionnel)"
                },
                "max_score": {
                    "type": "number",
                    "description": "Score CV maximum (0-100, optionnel)"
                },
                "status": {
                    "type": "string",
                    "description": "Statut pipeline : new, cv_uploaded, cv_analyzed, invited, consent_given, call_scheduled, call_in_progress, call_done, evaluated (optionnel)"
                },
                "search": {
                    "type": "string",
                    "description": "Texte libre pour rechercher dans nom, email (optionnel)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Nombre max de résultats (défaut: 20, max: 50)"
                }
            }
        }
    },
    {
        "name": "list_positions",
        "description": "Liste tous les postes ouverts ou archivés.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Statut du poste : active, closed, draft (optionnel)"
                },
                "search": {
                    "type": "string",
                    "description": "Texte libre pour rechercher dans titre/description (optionnel)"
                }
            }
        }
    },
    {
        "name": "get_position_details",
        "description": "Récupère les détails complets d'un poste spécifique (compétences requises, seniority, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "position_id": {
                    "type": "string",
                    "description": "UUID du poste (requis)"
                }
            },
            "required": ["position_id"]
        }
    },
    {
        "name": "get_candidate_details",
        "description": "Fiche complète d'un candidat : infos perso, CV parsé, scores, entretiens, rapports.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "string",
                    "description": "UUID du candidat (requis)"
                }
            },
            "required": ["candidate_id"]
        }
    },
    {
        "name": "get_analytics_overview",
        "description": "Vue d'ensemble des KPIs : total candidats, postes ouverts, taux conversion, score moyen, etc.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "aggregate_scores",
        "description": "Statistiques agrégées sur les scores (moyenne, min, max, distribution).",
        "input_schema": {
            "type": "object",
            "properties": {
                "score_type": {
                    "type": "string",
                    "description": "Type de score : cv_score, technical, experience, communication, global (requis)",
                    "enum": ["cv_score", "technical", "experience", "communication", "global"]
                },
                "position_id": {
                    "type": "string",
                    "description": "UUID du poste pour filtrer (optionnel)"
                }
            },
            "required": ["score_type"]
        }
    },
    {
        "name": "get_pipeline_breakdown",
        "description": "Répartition des candidats par statut pipeline (new, consent_pending, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "position_id": {
                    "type": "string",
                    "description": "UUID du poste pour filtrer (optionnel)"
                }
            }
        }
    },
    {
        "name": "export_data",
        "description": "Exporte des données en fichier Excel (.xlsx) téléchargeable. Utilise cet outil quand l'utilisateur demande un export, un téléchargement, un fichier Excel/CSV/XLS.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data_type": {
                    "type": "string",
                    "description": "Type de données à exporter",
                    "enum": ["candidates", "interviews", "positions"]
                },
                "position_id": {
                    "type": "string",
                    "description": "UUID du poste pour filtrer (optionnel)"
                },
                "status": {
                    "type": "string",
                    "description": "Statut pour filtrer : pour candidates = pipeline_status (evaluated, cv_analyzed, etc.), pour positions = active/draft/closed, pour interviews = completed/scheduled/etc. (optionnel)"
                },
                "min_score": {
                    "type": "number",
                    "description": "Score CV minimum pour filtrer les candidats (optionnel)"
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Colonnes spécifiques à inclure (optionnel, toutes par défaut)"
                },
                "filename": {
                    "type": "string",
                    "description": "Nom du fichier sans extension (optionnel, auto-généré sinon)"
                }
            },
            "required": ["data_type"]
        }
    }
]
