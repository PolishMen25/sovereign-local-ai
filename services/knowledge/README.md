# Knowledge interne

La cible est un service interne de consultation de connaissances validées, de
provenance et d'historique documentaire. Le prototype actuel fournit seulement
une recherche lexicale bornée dans les titres et résumés d'un catalogue JSONL ;
il ne constitue ni un index vectoriel, ni un RAG complet, ni un générateur de
réponses.

Il n'est ni routable ni publié vers Internet. Les écritures sont limitées à des workflows de promotion approuvés et audités.

## Prototype MCP local

`mcp_server.py` est un prototype **stdio-only** conforme au cycle de vie MCP `2025-06-18`. Il ne dépend d'aucune bibliothèque tierce, n'ouvre aucun port, n'exécute aucune commande et n'accepte jamais de chemin fourni par le client.

Les trois outils exposés sont :

- `knowledge_status`, qui révèle seulement l'état de préparation du catalogue ;
- `search_validated`, qui recherche dans un catalogue local `catalogue.jsonl` borné et retourne au plus cinq extraits avec leur `provenance_id`.
- `get_provenance`, qui retourne uniquement les identifiants et titres liés à
  une provenance exacte, sans accepter de chemin ni révéler un contenu complet.

Le répertoire du catalogue est défini par l'opérateur via `SOVEREIGN_KNOWLEDGE_ROOT` ; son défaut est `workbench/validated`. Le catalogue n'est jamais créé ou modifié par le serveur MCP. Avant toute exposition réseau, l'authentification, les ACL de service, la journalisation d'audit, la limitation de débit et l'allowlist des clients doivent être validées par ADR.

## Index hybride préparé

`hybrid_index.py` ajoute un index local reconstructible : métadonnées et FTS5
dans SQLite, vecteurs finis fournis par un moteur d'embeddings séparé et score
hybride borné. Le module ne télécharge rien, n'ouvre aucun socket et n'accepte
aucun chemin venant d'un client. Tant qu'aucun moteur d'embeddings vérifié
n'est installé, son résultat annonce explicitement le mode `lexical`.

