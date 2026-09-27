# Knowledge interne

> Mise à jour documentaire du 2026-09-27, contre `main` à `c0b169e` (code de
> ce dossier inchangé depuis `db9414d`, registre jusqu'à D-042). Ce
> document décrit le code, pas l'état installé : le serveur de calcul est hors
> ligne et le niveau de preuve de chaque capacité figure dans
> [`docs/project/current-capabilities.md`](../../docs/project/current-capabilities.md).

La cible est un service interne de consultation de connaissances validées, de
provenance et d'historique documentaire. Le dossier contient aujourd'hui deux
prototypes distincts : un serveur MCP `stdio` de recherche lexicale dans un
catalogue JSONL, et l'index hybride utilisé par la passerelle Web avec ses
modules de dépôt de documents. Ni le serveur MCP ni l'index ne génèrent de
réponse ; `document_analysis.py` orchestre toutefois une analyse map-reduce
d'un document déposé en appelant le runtime local de la passerelle, qui lui
est fourni comme fonction `generate`.

Il n'est ni routable ni publié vers Internet. Les écritures dans le catalogue
MCP sont limitées à des workflows de promotion approuvés et audités. Les
documents déposés depuis la passerelle rejoignent la table de l'index hybride
(voir plus bas) ; sans décision au registre, ce composant est à régulariser
selon `AGENTS.md`.

## Prototype MCP local

`mcp_server.py` est un prototype **stdio-only** conforme au cycle de vie MCP `2025-06-18`. Il ne dépend d'aucune bibliothèque tierce, n'ouvre aucun port, n'exécute aucune commande et n'accepte jamais de chemin fourni par le client.

Les trois outils exposés sont :

- `knowledge_status`, qui révèle seulement l'état de préparation du catalogue ;
- `search_validated`, qui recherche dans un catalogue local `catalogue.jsonl` borné et retourne au plus cinq extraits avec leur `provenance_id`.
- `get_provenance`, qui retourne uniquement les identifiants et titres liés à
  une provenance exacte, sans accepter de chemin ni révéler un contenu complet.

Le répertoire du catalogue est défini par l'opérateur via `SOVEREIGN_KNOWLEDGE_ROOT` ; son défaut est `workbench/validated`. Le catalogue n'est jamais créé ou modifié par le serveur MCP. Avant toute exposition réseau, l'authentification, les ACL de service, la journalisation d'audit, la limitation de débit et l'allowlist des clients doivent être validées par ADR.

## Index hybride

`hybrid_index.py` fournit un index local reconstructible : métadonnées et FTS5
dans SQLite, vecteurs finis d'au plus 1 024 dimensions fournis par un moteur
d'embeddings séparé et score hybride borné. Le module ne télécharge rien,
n'ouvre aucun socket et n'accepte aucun chemin venant d'un client.

- Sans vecteur de requête, la recherche est **lexicale** (BM25 FTS5) et le
  résultat annonce le mode `lexical`.
- Avec un vecteur de requête, le résultat annonce le mode `hybrid` : chaque
  passage vectorisé de même dimension est parcouru exhaustivement sur CPU et
  noté `0,45 × lexical + 0,55 × cosinus`. Cette pondération est codée en dur et
  n'a pas été mesurée ; aucun reranker n'existe dans le dépôt, et le reranker
  comme le moteur d'index restent à valider par benchmark (P-004).
- Le moteur d'embeddings raccordé par la passerelle est Qwen3-Embedding-0.6B
  servi par llama.cpp en boucle locale (`infra/embed/sovereign-embed.service`,
  `d7cc78c`) ; `tools/reembed_validated_chunks.py` calcule, de façon
  idempotente, les vecteurs des passages qui n'en ont pas. **Code présent,
  déploiement non vérifié.** D-028 autorise
  un petit moteur d'embeddings pré-entraîné sous réserve de licence et
  d'empreinte vérifiées, mais aucun lock de ce modèle n'est versionné dans
  `configs/runtime/` et aucune entrée du registre ne le désigne : composant à
  régulariser selon `AGENTS.md`, décision du propriétaire en attente.

## Documents déposés

`document_ingest.py`, `document_text.py` et `document_analysis.py` servent la
route `POST /v1/documents` de la passerelle (`010706c`, `5c917de`, code seul) :

- l'original, au plus 25 Mio, est conservé dans un dossier par document, puis
  découpé en au plus 400 passages de 1 200 caractères ;
- le texte est extrait en Python pour le texte brut et le `.docx`, et par
  sous-processus hors ligne `pdftotext`/`pdftoppm` (poppler) et `tesseract`
  pour le PDF et l'OCR ; leur présence sur le serveur n'est pas consignée ;
- chaque passage est écrit par `HybridKnowledgeIndex.upsert_validated` avec une
  provenance `upload:<id>`, dans la même table que le manifeste approuvé ;
- l'analyse map-reduce est bornée à 30 passages.

Une reconstruction de l'index approuvé par
`tools/build_project_knowledge_index.py` crée une base neuve limitée au
manifeste, sans embeddings, puis remplace le fichier : appliquée à la base de
la passerelle, elle effacerait les passages déposés et tous les embeddings.
Le niveau de confiance des documents déposés, l'isolement des extracteurs et
l'effet d'une reconstruction relèvent d'une décision du propriétaire.

## Chemins du corpus de l'arène

`corpus_paths.py` est la source unique des racines du corpus issu de l'arène,
lues par la passerelle et par les outils de construction et de promotion des
incréments. Il refuse d'écrire si le partage durable n'est pas monté, pour ne
pas créer un arbre local trompeur.

## Variables de configuration

| Variable | Lue par | Défaut dans le code | Effet |
| --- | --- | --- | --- |
| `SOVEREIGN_KNOWLEDGE_ROOT` | `mcp_server.py` | `workbench/validated`, résolu depuis le répertoire courant | Dossier du catalogue `catalogue.jsonl` du serveur MCP. |
| `SOVEREIGN_CORPUS_RAW_ROOT` | `corpus_paths.py` | `<partage>/raw/corpus/arena` | Racine RAW des incréments de l'arène. |
| `SOVEREIGN_CORPUS_VALIDATED_ROOT` | `corpus_paths.py` | `<partage>/validated/corpus/arena-increments` | Racine des incréments promus. |

`<partage>` est le point de montage du partage durable dans le conteneur,
défini par `CONTAINER_SHARE` dans `corpus_paths.py`. Les variables de la
passerelle qui pilotent l'index et les documents (`SOVEREIGN_WEB_STATE`,
`SOVEREIGN_EMBED_ENDPOINT`, `SOVEREIGN_DOCUMENTS_DIR`) sont décrites dans
[`services/web/README.md`](../web/README.md).
