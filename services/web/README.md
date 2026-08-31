# Interface Web interne

Future interface de chat, historique, citations et suivi des tâches pour les utilisateurs autorisés. Son framework, son hébergement et son identité restent ouverts ; IIS est une possibilité à confirmer, pas une décision.

L'interface ne fournit aucun tunnel permettant à IA-CORE de contacter Internet.

## Contrat de préparation

Les échanges de la future interface suivent les schémas
`schemas/local-chat-request.schema.json` et
`schemas/local-chat-response.schema.json`. Une requête porte un identifiant de
corrélation, un message borné, un profil logique facultatif et des références
de contexte explicites. Une réponse distingue son état, ses citations de
provenance et ses propositions ; chaque proposition exige `requires_confirmation:
true`.

Le premier écran prévu est volontairement simple : sélection d'un profil,
conversation, citations repliables, état de la tâche et bouton de confirmation
séparé. Aucun secret, chemin arbitraire, commande ou action externe ne doit être
transmis par le navigateur. Le framework, l'authentification, l'hébergement et
le port restent à décider par ADR ; aucun serveur web n'est démarré par ce
contrat.

