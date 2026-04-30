# Alembic — Migrations de schéma

## Principes

Depuis le **Chantier 12** (avril 2026), alembic est la **source de vérité unique** du schéma de base. Toute modification de schéma passe par une revision alembic, reviewée et mergée comme du code.

**Règles :**

1. **Une seule `head`** en permanence. Si tu crées une revision depuis une branche et qu'un collègue en a créé une autre en parallèle sur main, la CI t'attrape. Tu dois alors créer une revision de merge (`alembic merge`) avant de re-push.
2. **Jamais de `Base.metadata.create_all()` en prod**, ni dans du code qui tourne au démarrage de l'app. C'est ce qui avait cassé la chaîne alembic historique (voir `archive/README.md`). La seule exception autorisée est `tests/conftest.py` qui utilise `create_all/drop_all` pour les tests.
3. **Toute colonne ajoutée/supprimée/renommée** → revision alembic. Pas d'`ALTER TABLE` manuel sur une DB.
4. **Les revisions sont écrites à la main ou auto-générées**, puis **relues avant commit**. Un `--autogenerate` n'est jamais livré sans relecture.

## Workflow quotidien

### Ajouter une modif schéma

1. Modifier le modèle SQLAlchemy dans `app/models/<xxx>.py`.
2. Générer la revision :

   ```bash
   alembic revision --autogenerate -m "add_position_sla_and_level"
   ```

3. **Relire** le fichier généré dans `alembic/versions/<hash>_add_position_sla_and_level.py`. Vérifier :
   - Les colonnes/tables visées sont bien les bonnes (pas de dommage collatéral sur des tables voisines).
   - Les types Postgres sont corrects (`JSONB`, `UUID(as_uuid=True)`, `Enum`, `ARRAY`, etc.).
   - Les `server_default` et `nullable` sont cohérents avec le modèle.
   - La fonction `downgrade()` est réversible.
4. Tester localement :

   ```bash
   alembic upgrade head        # applique
   alembic downgrade -1        # annule (doit être propre)
   alembic upgrade head        # ré-applique
   ```

5. Commit la revision + le modèle dans le même commit, avec un message descriptif.

### Sur une nouvelle machine / déploiement neuf

```bash
alembic upgrade head         # crée les 22 tables via la baseline + revisions ultérieures
python scripts/init_db.py    # seed de démo (idempotent)
```

`init_db.py` refuse de tourner si `alembic_version` n'est pas stampée — c'est voulu, c'est le garde-fou qui empêche de re-tomber dans le piège du `create_all`.

### Rollback d'urgence

```bash
alembic downgrade -1         # revient d'une revision
alembic downgrade <hash>     # revient à une revision précise
alembic downgrade base       # drop tout (uniquement en local / DB jetable)
```

## Commandes de référence

| But | Commande |
| --- | --- |
| Voir la revision stampée sur la DB | `alembic current` |
| Voir l'historique | `alembic history --verbose` |
| Voir le/les head(s) | `alembic heads` |
| Créer une revision vide (DDL manuel) | `alembic revision -m "message"` |
| Créer via autogenerate | `alembic revision --autogenerate -m "message"` |
| Appliquer jusqu'au head | `alembic upgrade head` |
| Stamp sans exécuter | `alembic stamp <rev>` (⚠️ usage rare) |

## Anti-patterns à bannir

- ❌ `Base.metadata.create_all(engine)` en prod ou dans du code de démarrage.
- ❌ Éditer une revision déjà appliquée sur un environnement partagé. Toujours créer une revision *corrective*.
- ❌ Supprimer un fichier de revision du dossier `versions/` (casse la chaîne). Pour retirer une revision, la `downgrade` d'abord, puis `alembic revision --autogenerate` produit le code.
- ❌ Laisser plusieurs heads durablement. Une revision de merge doit être créée au merge de la PR (`alembic merge head1 head2 -m "merge_feature_x"`).

## Historique

Voir `archive/README.md` pour le contexte de la remise à plat (22 revisions legacy qui n'avaient jamais tourné, dette résolue au Chantier 12).

La revision baseline `09607bb8eb7d_baseline_2026_04_post_reset.py` est le point de départ de l'histoire alembic "réelle" du projet. Toute revision postérieure s'enchaîne dessus.
