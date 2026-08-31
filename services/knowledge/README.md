# Knowledge interne

La cible est un service interne de consultation de connaissances validées, de
provenance et d'historique documentaire. Le prototype actuel fournit seulement
une recherche lexicale bornée dans les titres et résumés d'un catalogue JSONL ;
il ne constitue ni un index vectoriel, ni un RAG complet, ni un générateur de
réponses.

Il n'est ni routable ni publié vers Internet. Les écritures sont limitées à des workflows de promotion approuvés et audités.

## Prototype MCP local

`mcp_server.py` est un prototype **stdio-only** conforme au cycle de vie MCP `2025-06-18`. Il ne dépend d'aucune bibliothèque tierce, n'ouvre aucun port, n'exécute aucune commande et n'accepte jamais de chemin fourni par le client.

Les deux outils exposés sont :

- `knowledge_status`, qui révèle seulement l'état de préparation du catalogue ;
- `search_validated`, qui recherche dans un catalogue local `catalogue.jsonl` borné et retourne au plus cinq extraits avec leur `provenance_id`.

Le répertoire du catalogue est défini par l'opérateur via `SOVEREIGN_KNOWLEDGE_ROOT` ; son défaut est `workbench/validated`. Le catalogue n'est jamais créé ou modifié par le serveur MCP. Avant toute exposition réseau, l'authentification, les ACL de service, la journalisation d'audit, la limitation de débit et l'allowlist des clients doivent être validées par ADR.

