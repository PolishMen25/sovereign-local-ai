# Interface Web interne

Future interface de chat, historique, citations et suivi des tâches pour les utilisateurs autorisés. Son framework, son hébergement et son identité restent ouverts ; IIS est une possibilité à confirmer, pas une décision.

L'interface ne fournit aucun tunnel permettant à IA-CORE de contacter Internet.

## Contrat de préparation

Les échanges cibles de la future interface sont décrits par les schémas
`schemas/local-chat-request.schema.json` et
`schemas/local-chat-response.schema.json`. Une requête porte un identifiant de
corrélation, un message borné, un profil logique facultatif et des références
de contexte explicites. Une réponse distingue son état, ses citations de
provenance et ses propositions ; chaque proposition exige `requires_confirmation:
true`.

Le prototype actuel ne réalise qu'une validation partielle du contrat d'entrée
(version, identifiant et taille du message). Il n'est donc pas présenté comme
un validateur complet du schéma.

Le premier écran prévu est volontairement simple : sélection d'un profil,
conversation, citations repliables, état de la tâche et bouton de confirmation
séparé. Aucun secret, chemin arbitraire, commande ou action externe ne doit être
transmis par le navigateur. Le framework, l'authentification, l'hébergement et
le port restent à décider par ADR ; aucun serveur web n'est démarré par ce
contrat.

Le prototype `app.py` peut être lancé uniquement pour un essai local avec un
jeton injecté hors dépôt (`SOVEREIGN_WEB_TOKEN`) ; il force une écoute loopback.
Il ne charge pas encore le registre d'agents, l'autorisation par rôles, le MCP
Knowledge ou le runtime d'inférence. `POST /v1/chat` renvoie donc toujours HTTP
`503` avec `local inference is not ready`. Il ne constitue pas une exposition
de production ni une interface de conversation utilisable.

