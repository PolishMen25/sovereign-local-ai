# Interface Web interne

> Mise à jour documentaire du 2026-09-27, contre `main` à `c0b169e`
> (interrupteur D-035 inclus, registre jusqu'à D-042). Ce document décrit le
> code de la passerelle, pas l'état installé : le serveur de
> calcul est hors ligne et le dernier relevé en direct date du 2026-09-09. Le
> niveau de preuve de chaque capacité figure dans
> [`docs/project/current-capabilities.md`](../../docs/project/current-capabilities.md).

L'interface fournit une première configuration locale, une authentification
Argon2id, des sessions avec cookie sécurisé et CSRF, un chat relié à trois
moteurs, ainsi que la liste, l'export et la suppression des conversations
privées. Le code y ajoute le dépôt de documents, une boucle d'outils, des
actions confirmables, des profils sélectionnables et les pages `/arena`,
`/corpus` et `/sante`. Elle reste un sas distinct de CORE.

`app.py` force une écoute loopback. Le secret de première installation est
injecté hors dépôt par `SOVEREIGN_SETUP_TOKEN` et contient au moins 32
caractères. Les bases d'authentification, de mémoire et de connaissances sont
placées sous le répertoire opérateur `SOVEREIGN_WEB_STATE`. Une absence
d'Argon2id ou d'un runtime provoque un refus sûr ; aucun fournisseur distant
n'est utilisé.

Le service ne doit jamais écouter directement sur le LAN. Un reverse proxy
HTTPS approuvé porte l'accès LAN ou tailnet, tandis que le processus Python
reste sur `127.0.0.1`.

## Moteurs

`engines()` expose trois moteurs ; le champ `engine` de chaque réponse vaut
`BOOTSTRAP`, `CORE-700M`, `QWEN-CODER` ou `unavailable`. Il est interdit de
présenter BOOTSTRAP comme CORE. Les requêtes et réponses suivent les schémas
`local-chat-request.v1` et `local-assistant-response.v1`. **Écart code/schéma
non corrigé ici** : `schemas/local-chat-response.schema.json` n'énumère pas
encore `QWEN-CODER`.

| Moteur | Client | Condition d'emploi | Remarque |
| --- | --- | --- | --- |
| `BOOTSTRAP` | `bootstrap_client.py` : HTTP loopback seulement, sans proxy ni redirection | Toujours tenté ; moteur par défaut | L'interface et `/sante` le libellent « CHAT-14B · Qwen2.5-14B », alors que le dépôt ne verrouille que Qwen2.5-1.5B (lock et unité avec `--no-agent`). Aucun lock, licence, unité ni entrée du registre pour un 14B : composant à régulariser selon `AGENTS.md`, décision du propriétaire en attente. |
| `QWEN-CODER` | `qwen_client.py` : point d'accès privé épinglé par égalité exacte | `SOVEREIGN_QWEN_TOKEN` d'au moins 32 caractères ; sinon le moteur est « non configuré » et la route répond 503 | Promu le 2026-09-10 (D-034, ADR-0005). |
| `CORE-700M` | `core_client.py` : point d'accès privé épinglé par égalité exacte | `SOVEREIGN_CORE_TOKEN` d'au moins 32 caractères ; sinon moteur indisponible | Expérimental ; voie archivée par D-034, aucun palier long. |

L'épinglage des clients CORE et Qwen est un contrôle de sécurité. Lorsque le
jeton correspondant est fourni (au moins 32 caractères), toute autre valeur de
`SOVEREIGN_CORE_ENDPOINT` ou `SOVEREIGN_QWEN_ENDPOINT` fait échouer le
démarrage de la passerelle ; sans ce jeton, la variable n'est pas lue et le
moteur reste indisponible ou non configuré. Les valeurs épinglées sont des
adresses privées codées dans le client, non recopiées ici. D-036 décide de les
sortir du dépôt vers une configuration privée hors Git, avec échec fermé et
épinglage exact conservé ; ce code n'est pas encore livré.

## Connaissances, documents et embeddings

La route de chat interroge l'index SQLite/FTS5 local
(`services/knowledge/hybrid_index.py`), au plus 6 extraits. Les extraits sont
bornés, leur provenance est renvoyée dans `citations` et ils sont présentés au
modèle comme des données non exécutables.

- **Recherche hybride** (`d7cc78c`, code présent, déploiement non vérifié) :
  quand `SOVEREIGN_EMBED_ENDPOINT` répond, le score combine 0,45 lexical et
  0,55 vectoriel, pondération codée en dur et non mesurée ; sinon le mode reste
  lexical. Le client d'embeddings n'accepte que la boucle locale avec un port
  explicite. D-028 autorise un petit moteur d'embeddings sous réserve de
  licence et d'empreinte vérifiées, mais aucun lock de Qwen3-Embedding-0.6B
  n'est versionné : composant à régulariser selon `AGENTS.md`, décision du
  propriétaire en attente. Le champ `rag_mode`
  de `/v1/session` et des métadonnées de flux reste fixé à `lexical` (ou
  `tools`), même quand la recherche est hybride.
- **Documents partagés** (`010706c`, `5c917de`, code seul) : `POST
  /v1/documents` accepte au plus 25 Mio. L'original est conservé sous
  `SOVEREIGN_DOCUMENTS_DIR`. Le texte est extrait en Python pour le texte et le
  `.docx`, et par sous-processus `pdftotext`/`pdftoppm` (poppler) et
  `tesseract` pour le PDF et l'OCR. La présence de ces outils sur le serveur
  n'est pas consignée. `POST /v1/documents/analyze` produit une analyse
  map-reduce bornée à 30 passages.
- **Frontière de confiance** : les passages déposés entrent par
  `HybridKnowledgeIndex.upsert_validated` dans la même table que le manifeste
  approuvé. Sans décision au registre : `AGENTS.md` range l'analyse et le
  téléversement de documents parmi les composants à régulariser, et leur
  niveau de confiance comme l'isolement des extracteurs relèvent du
  propriétaire.

## Outils et actions du chat

- **Boucle d'outils en lecture seule** (`a133659`, code seul) :
  `search_knowledge`, `list_documents`, `read_document` et `current_time`,
  sans système de fichiers arbitraire, shell ni réseau. Elle s'engage pour le
  profil `coordination` et les profils du catalogue marqués avec outils,
  seulement sur `BOOTSTRAP`, en réponse `text/event-stream`, et tant que
  `SOVEREIGN_TOOLS_ENABLED` n'est pas désactivé. Elle exige un serveur
  llama.cpp lancé avec `--jinja`, dont l'unité n'est pas versionnée. D-024
  exclut outil, agent et RAG pour BOOTSTRAP ; sans décision au registre, à
  régulariser selon `AGENTS.md`.
- **Actions** (`04473fe`, `3410b36`, code seul) : `run_python` dans le bac à
  sable bwrap et `write_file` dans l'espace de travail. Le modèle ne fait que
  proposer ; rien ne s'exécute avant une confirmation humaine à usage unique
  par `POST /v1/chat/confirm`. Une proposition en attente expire après
  15 minutes et 100 au plus sont conservées. Les fichiers produits sont listés
  par `GET /v1/workspace` et téléchargeables par `GET /v1/workspace/<chemin>`.
- **Interrupteur D-035** (`c0b169e`, code seul, non déployé) : les actions
  sont désactivées par défaut et ne s'activent qu'avec
  `SOVEREIGN_ACTIONS_ENABLED=1` ; détail dans la section « Actions du chat »
  plus bas. D-035 accepte que l'installation en service garde son
  comportement antérieur jusqu'au déploiement de ce code ; leur réactivation
  exige une décision distincte.
- **Conditions dans le code.** Une action n'est offerte au modèle que si
  toutes ces conditions sont réunies :
  1. `SOVEREIGN_ACTIONS_ENABLED=1` au démarrage (D-035) ;
  2. `SOVEREIGN_TOOLS_ENABLED`, qui coupe toute la boucle d'outils, actions
     comprises ;
  3. pour `run_python`, l'auto-test du bac à sable : l'action n'est proposée
     que si une exécution réelle réussit, verdict mis en cache ; interrupteur
     coupé, cet auto-test n'est pas lancé ;
  4. pour `write_file`, un dossier de travail configuré, ce que `main()` fait
     toujours.
- **HYPOTHÈSE à vérifier sur le serveur** : l'unité versionnée
  `infra/gateway/sovereign-gateway-web.service` garde `PrivateDevices=yes` et
  n'autorise pas `AF_NETLINK`, contrairement à l'unité de l'arène qui les
  écarte pour bwrap ; interrupteur activé, l'auto-test échouerait sous cette
  unité et `run_python` ne serait pas proposé.

## Profils

`GET /v1/profiles` renvoie le profil intégré `coordination`, les 59 profils du
catalogue `configs/agents/registry.json` et les agents d'arène approuvés pour
le chat. Le moteur suit la famille : `development` utilise `QWEN-CODER` (10
profils), les autres `BOOTSTRAP` avec boucle d'outils (49 profils). Les gates
d'évaluation par profil ne sont pas appliqués ; seul le commentaire de
`catalog_profiles.py` l'attribue à un choix du propriétaire, et le registre
garde les 60 profils en `draft` : sans décision au registre, à régulariser
selon `AGENTS.md`. La description du profil `coordination` dans `app.py`
affirme encore que les profils du catalogue restent désactivés, ce que le
code contredit.

## Arène et corpus

- `GET /v1/arena` et `GET /v1/arena/events` lisent la base de l'arène ouverte
  en lecture seule ; `POST /v1/arena/approve` dépose une approbation de paquet
  (avec son SHA-256) ou de profil pour le chat dans `SOVEREIGN_ARENA_INBOX`.
- `GET /v1/corpus/increments` liste les incréments RAW et leur statut ;
  `POST /v1/corpus/promote` dépose une approbation dans
  `SOVEREIGN_CORPUS_INBOX`. Un service périodique (`infra/corpus/`, toutes les
  2 minutes) vérifie l'identifiant, l'empreinte du contenu et la présence d'un
  approbateur, puis promeut l'incrément RAW vers VALIDATED en reportant son
  plafond de part synthétique, 20 % par défaut. La passerelle n'écrit jamais le
  corpus et rien ne déclenche d'entraînement. D-040 plafonne le synthétique à
  20 % des tokens d'une version de corpus et n'admet que le code généré par
  Qwen2.5-Coder ; les validateurs de corpus ne sont pas encore alignés sur
  cette règle.
- **Format des approbations.** Ce sont des fichiers JSON (`schema_version`,
  `kind`, `target_id`, `target_sha256` le cas échéant, `approved_by` issu de la
  session, `approved_at`) créés en exclusif avec le mode `0640`. Leur modèle
  de confiance relève de la régularisation de l'arène et de la boucle
  d'auto-entraînement demandée par `AGENTS.md`.

## Interface et routes

Les fichiers statiques locaux de `services/web/static/` fournissent la
première configuration, la connexion, l'historique réouvrable, l'export, la
suppression et les pages `/arena`, `/corpus` et `/sante`. Ils n'utilisent ni
bibliothèque distante, ni stockage de mot de passe ou de conversation dans le
navigateur.

Sans session, seuls les fichiers statiques, `GET /healthz` et
`GET /v1/setup-status` répondent. Après connexion, les routes `GET` sont
`/v1/session`, `/v1/profiles`, `/v1/engines`, `/v1/knowledge-status`,
`/v1/conversations` et l'export d'une conversation, `/v1/arena`,
`/v1/arena/events`, `/v1/corpus/increments`, `/v1/workspace` et `/v1/health`.
Les routes `POST` authentifiées exigent le jeton CSRF, hors connexion et
première configuration.

Une réponse de chat peut être demandée avec `Accept: text/event-stream` : le
serveur publie les métadonnées, puis des événements `delta` quand BOOTSTRAP
répond hors boucle d'outils et hors profil du catalogue, et enfin la réponse
complète.

## Variables de configuration

Variables `SOVEREIGN_*` lues par la passerelle (`app.py`, et
`services/knowledge/corpus_paths.py` qu'elle importe). Les valeurs par défaut
sont celles du code ; `<état>` désigne la valeur de `SOVEREIGN_WEB_STATE`.

| Variable | Défaut dans le code | Effet |
| --- | --- | --- |
| `SOVEREIGN_WEB_HOST` | `127.0.0.1` | Adresse d'écoute ; toute valeur autre que `127.0.0.1`, `::1` ou `localhost` arrête le démarrage. |
| `SOVEREIGN_WEB_PORT` | `8765` | Port d'écoute en boucle locale. |
| `SOVEREIGN_WEB_STATE` | `/var/lib/sovereign-gateway` | Répertoire d'état : `authentication.sqlite3`, `memory.sqlite3`, `knowledge.sqlite3` et dossiers par défaut ci-dessous. |
| `SOVEREIGN_SETUP_TOKEN` | aucun (vide) | Secret de première configuration ; moins de 32 caractères arrête le démarrage. |
| `SOVEREIGN_BOOTSTRAP_ENDPOINT` | `http://127.0.0.1:8080` | Runtime BOOTSTRAP ; boucle locale imposée par le client. |
| `SOVEREIGN_CORE_TOKEN` | aucun (vide) | Moins de 32 caractères : CORE-700M reste indisponible. |
| `SOVEREIGN_CORE_ENDPOINT` | adresse privée épinglée, non recopiée | Toute autre valeur fait échouer le démarrage si le jeton CORE est fourni. |
| `SOVEREIGN_QWEN_TOKEN` | aucun (vide) | Moins de 32 caractères : `QWEN-CODER` non configuré, réponse 503. |
| `SOVEREIGN_QWEN_ENDPOINT` | adresse privée épinglée, non recopiée | Toute autre valeur fait échouer le démarrage si le jeton Qwen est fourni. |
| `SOVEREIGN_EMBED_ENDPOINT` | `http://127.0.0.1:8082` | Runtime d'embeddings en boucle locale ; une valeur vide désactive le client et laisse la recherche lexicale. |
| `SOVEREIGN_TOOLS_ENABLED` | `1` | Boucle d'outils et actions ; désactivée seulement par `0`, `false`, `no` ou une valeur vide, sensible à la casse. |
| `SOVEREIGN_ACTIONS_ENABLED` | absente : actions désactivées | Interrupteur D-035, lu une fois au démarrage ; seule la valeur exacte `1` active `run_python` et `write_file`. |
| `SOVEREIGN_DOCUMENTS_DIR` | `<état>/documents` | Originaux et texte extrait des documents déposés ; créé au démarrage. |
| `SOVEREIGN_WORKSPACE_DIR` | `<état>/workspace` | Espace de travail de `write_file` ; créé au démarrage. |
| `SOVEREIGN_CORPUS_INBOX` | `<état>/corpus-inbox` | Dépôt des approbations d'incréments pour l'applicateur ; créé au démarrage. |
| `SOVEREIGN_CORPUS_RAW_ROOT` | `<partage>/raw/corpus/arena` | Incréments RAW de l'arène, lus par `/v1/corpus/increments`. |
| `SOVEREIGN_CORPUS_VALIDATED_ROOT` | `<partage>/validated/corpus/arena-increments` | Incréments promus, lus pour le statut. |
| `SOVEREIGN_ARENA_DB` | `/var/lib/sovereign-arena/arena.sqlite3` | Base de l'arène, ouverte en lecture seule. |
| `SOVEREIGN_ARENA_INBOX` | `/var/lib/sovereign-arena/inbox` | Dépôt des approbations de paquets et de profils. |
| `SOVEREIGN_AGENT_REGISTRY` | `configs/agents/registry.json` | Registre des profils, chemin relatif au répertoire courant du processus. |

`<partage>` est le point de montage du partage durable dans le conteneur de la
passerelle, défini par `CONTAINER_SHARE` dans
`services/knowledge/corpus_paths.py`. `tools/reembed_validated_chunks.py` lit
aussi `SOVEREIGN_WEB_STATE` et `SOVEREIGN_EMBED_ENDPOINT`, avec les mêmes
défauts. Les variables propres au démon de l'arène (`SOVEREIGN_ARENA_SUITE`,
etc.) ne sont pas lues par la passerelle.

## Actions du chat : `SOVEREIGN_ACTIONS_ENABLED` (D-035)

Les actions sont les outils à effet de bord : `run_python` (bac à sable hors
ligne) et `write_file` (dossier de travail de la passerelle). Elles sont
**désactivées par défaut**. La variable est lue une seule fois au démarrage :
seule la valeur exacte `1` les active ; absente, vide ou `0` les désactive ;
toute autre valeur (`true`, `yes`, ` 1`…) les désactive et journalise un
avertissement qui ne recopie pas la valeur.

Désactivées, les actions ne sont ni annoncées ni offertes au modèle ; toute
proposition, confirmation (`POST /v1/chat/confirm` répond `403
actions_disabled`, y compris pour une action en attente ou un identifiant
forgé) ou exécution est refusée et journalisée sans contenu. `GET /v1/session`
et `GET /v1/health` exposent le booléen `actions_enabled`. Les outils en lecture
seule (recherche, documents, heure, liste du dossier de travail) ne changent pas.
Activées, une action approuvée qui échoue côté système (erreur d'écriture, bac à
sable introuvable) renvoie au modèle un texte fixe, sans chemin du serveur ; le
journal n'en garde que la classe d'erreur (`event=action_failed`).

Déploiement : l'installation en service garde son comportement actuel tant que
ce code n'est pas déployé. Une fois déployé, les actions sont coupées ; les
conserver exige `SOVEREIGN_ACTIONS_ENABLED=1` dans l'environnement hors dépôt de
l'unité systemd de la passerelle, ce que D-035 soumet à une décision distincte.

## Reconstruction contrôlée de l'index

`tools.build_project_knowledge_index` n'indexe plus récursivement un dossier au
démarrage. La procédure requiert un manifeste candidat, son empreinte et une
référence de validation hors dépôt :

```bash
python3 -B -m tools.build_project_knowledge_index manifest \
  --source-directory docs \
  --document project/current-capabilities.md \
  --output /var/lib/sovereign-gateway/knowledge.candidate.json

# Après approbation humaine de l'empreinte affichée :
python3 -B -m tools.build_project_knowledge_index build \
  --source-directory docs \
  --manifest /var/lib/sovereign-gateway/knowledge.candidate.json \
  --approved-manifest-sha256 '<empreinte-approuvee>' \
  --approval-reference '<reference-audit>' \
  --database /var/lib/sovereign-gateway/knowledge.sqlite3
```

La seconde commande compare les octets de chaque source, puis remplace la base
SQLite atomiquement. Elle doit être exécutée lorsque la passerelle est arrêtée
proprement ; elle ne valide, ne télécharge ni ne promeut aucune donnée elle-même.

**Attention** : la base neuve ne contient que le manifeste, sans embeddings.
Appliquée à la base de la passerelle, la reconstruction efface donc les
passages des documents déposés et tous les embeddings. Le sort des documents
déposés relève d'une décision du propriétaire, à prendre avant toute
reconstruction.
