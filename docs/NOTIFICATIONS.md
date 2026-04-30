# Notifications system — AIHM

**Status** : production-ready, sprint 1 (avril 2026)
**Auteur** : Zakaria + Claude

## Vue d'ensemble

```
[Worker / Endpoint async] ──INSERT── [Postgres notifications]
            │
            └──redis.publish(notif:user:X)──┐
                                            │
[FastAPI GET /notifications/stream] ←── (subscribe Redis)
            │
            └── SSE event ──→ [Browser fetch-event-source]
                                        │
                                        └── NotificationContext
                                                ├── badge counter
                                                ├── toast
                                                └── browser Notification API
```

## Composants

### Backend

| Fichier | Rôle |
|---|---|
| `models/notification.py` | Table `notifications` (source de vérité) |
| `services/notification_service.py` | `create_notification(...)` — INSERT + auto-publish Redis |
| `services/notification_pubsub.py` | Helpers Redis pub/sub (sync pour workers, async pour endpoints) |
| `api/v1/notifications.py` | CRUD + endpoint SSE `/notifications/stream` |

### Frontend

| Fichier | Rôle |
|---|---|
| `contexts/NotificationContext` | Source unique. Combine SSE + fallback polling |
| `hooks/useNotificationStream` | Wrapper `@microsoft/fetch-event-source` |
| `components/NotificationBell` | Header bell + badge unread |

## Cycle de vie d'une notification

1. **Émission** — un worker Celery (ou un endpoint async) appelle :
   ```python
   from app.services.notification_service import create_notification

   create_notification(
       session=session,
       tenant_id=candidate.tenant_id,
       user_id=creator_user_id,  # None = broadcast tenant
       type="candidate.cv_analyzed",
       title="CV analysé : Alice Martin",
       message="Score 78/100 · Senior Python Dev",
       data={"candidate_id": "...", "cv_score": 78},
   )
   ```

2. **Persistance** — un row par destinataire est inséré dans `notifications`.

3. **Push** — chaque INSERT déclenche `redis.publish('notif:user:{id}', payload)`.
   Le payload est un JSON serialisé complet de la notification.

4. **Stream** — `GET /notifications/stream` (SSE) yield l'event au browser
   en temps réel (~100 ms).

5. **Fallback** — si SSE est down, le client peut toujours récupérer les notifs
   via `GET /notifications` (paginated). La DB reste la source de vérité.

## Types de notifications officiels

Convention : `{entity}.{event}` (snake_case ou kebab, à préférer point-séparé).

| Type | Émetteur | Destinataire | `data` payload |
|---|---|---|---|
| `candidate.cv_analyzed` | worker `cv.process` | créateur | `{candidate_id, cv_score, pipeline_status, position_id}` |
| `candidate.cv_failed` | worker `cv.process` | créateur | `{candidate_id, error}` |
| `auto_flagged_for_review` | worker `cv.process` | broadcast tenant | `{candidate_id, score, threshold}` |
| `bulk_import.completed` | worker `bulk_import` | uploadeur | `{import_id, total, success, failed}` |

**À ajouter dans les sprints suivants** :

| Type | Trigger | Use-case |
|---|---|---|
| `approval.requested` | endpoint `/approvals` POST | approver doit décider |
| `approval.decided` | endpoint `/approvals/{id}/decide` | requester est notifié |
| `comment.mention` | endpoint `/candidates/{id}/comments` POST | user @-mentionné |
| `interview.scheduled` | endpoint `/interviews` POST | candidat + recruteur |
| `offer.viewed` | webhook signataire | recruteur |
| `offer.signed` | webhook signataire | recruteur + admin |
| `position.workflow.approved` | endpoint `/positions/{id}/approve` | requester |

## Comment ajouter une nouvelle notif

1. Choisir un type clair (`{entity}.{event}`).
2. Documenter dans le tableau ci-dessus.
3. Au point d'émission, appeler `create_notification(session, ...)`.
4. Côté frontend (`NotificationContext`), si la notif a une action spécifique
   (ex: ouvrir un modal, naviguer vers une page), ajouter la logique dans
   `handleIncomingNotification(notif)`.

## Canaux Redis utilisés

- `notif:user:{user_id}` — push à un user spécifique
- `notif:tenant:{tenant_id}` — broadcast à tous les users du tenant
  (à utiliser **avec parcimonie** pour éviter le spam ; préférer
  `user_id=None` qui boucle sur les admins+recruteurs et crée une notif par user)

DB Redis : **4** (dédiée pour ne pas polluer Celery 1/2 ni cache 0).

## Heartbeat & reconnexion

- Côté serveur : `: ping\n\n` toutes les 15 s sur le stream SSE
  (commentaire SSE, ignoré par le client). Évite que les proxies coupent.
- Côté client : `@microsoft/fetch-event-source` reconnecte auto avec
  backoff exponentiel. Si 3 reconnects échouent, fallback polling 30 s.

## Sécurité

- L'endpoint `/stream` exige un Bearer token JWT valide (header Authorization).
- Pas de query param `?token=` (loggé dans access logs).
- Une connexion = un user. Pas d'écoute de canaux d'autres users.

## Observabilité

Logs structurés `structlog` :
- `notification_created` (INSERT OK)
- `notifications_created_bulk` (broadcast tenant)
- `notif_pubsub_publish_user_failed` (Redis down — non bloquant)
- `sse_client_disconnected` (déconnexion propre)
- `sse_stream_unexpected_error` (erreur à investiguer)

## Limites connues

- **Scaling horizontal** : OK avec Redis pub/sub (chaque instance FastAPI relaye
  ses propres clients).
- **Rate-limit SSE** : à ajouter sprint 2 (max 3 connexions simultanées par user).
- **Persistance des events SSE manqués** : non implémenté (pas Last-Event-ID).
  Le client rattrape via `GET /notifications` au reconnect.
- **Latence** : ~100 ms en local, ~500 ms via internet selon le RTT.
