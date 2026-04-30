"""Email templates for offer workflow."""

OFFER_SENT_TEMPLATE = {
    "subject": "Nouvelle offre d'emploi - {position_title}",
    "body": """
Bonjour {candidate_name},

Nous sommes heureux de vous soumettre une offre d'emploi pour le poste de {position_title}.

Détails de l'offre:
- Salaire: {salary_min} - {salary_max} {currency}
- Type de contrat: {contract_type}
- Date de début: {start_date}
- Avantages: {benefits}

Pour accepter cette offre, veuillez cliquer sur le lien ci-dessous:
{signature_link}

Cette offre expire le {expires_at}.

Cordialement,
{company_name}
""",
}

OFFER_REMINDER_TEMPLATE = {
    "subject": "Rappel: Offre d'emploi à signer - {position_title}",
    "body": """
Bonjour {candidate_name},

C'est un rappel concernant l'offre d'emploi pour le poste de {position_title}.

Si vous n'avez pas encore signé, veuillez cliquer sur le lien ci-dessous:
{signature_link}

Cette offre expire le {expires_at}.

Cordialement,
{company_name}
""",
}

OFFER_SIGNED_TEMPLATE = {
    "subject": "Offre acceptée - {position_title}",
    "body": """
Bonjour {company_name},

Félicitations! {candidate_name} a accepté l'offre pour le poste de {position_title}.

Détails:
- Candidat: {candidate_name}
- Email: {candidate_email}
- Signé le: {signed_at}

Prochaines étapes:
1. Vérifier les documents signés
2. Préparer l'onboarding
3. Communiquer la date de début

Cordialement,
Système AIHM
""",
}

OFFER_REJECTED_TEMPLATE = {
    "subject": "Offre déclinée - {position_title}",
    "body": """
Bonjour {company_name},

{candidate_name} a décliné l'offre pour le poste de {position_title}.

Raison: {rejection_reason}

Vous pouvez maintenant:
1. Contacter le candidat alternatif
2. Afficher le poste pour d'autres candidats
3. Relancer le processus de recrutement

Cordialement,
Système AIHM
""",
}
