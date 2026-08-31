# Préparation de l'orchestrateur IA-CORE

La cible future choisira un profil, appliquera ses permissions, appellera les
outils internes autorisés et partagera un petit nombre de moteurs de modèle.
Aujourd'hui, le code charge le registre et prépare une enveloppe de requête en
refusant les profils inconnus, invalides ou désactivés. Il n'appelle aucun
modèle, outil, réseau, fichier ou secret.

Il ne crée pas une copie du modèle par agent et ne dispose d'aucun outil générique lui permettant de contourner les frontières réseau ou données.

## Registre initial

Le registre versionné des 60 profils logiques se trouve dans
`configs/agents/registry.json`. Tous les profils sont livrés en statut `draft`,
avec `proposal_only`, mémoire non persistante et une allowlist MCP bornée. Le
registre est une spécification de préparation : il n'active aucun agent et ne
déploie pas d'ordonnanceur tant que les gates d'architecture et d'identité ne
sont pas approuvés.

L'ordonnanceur devra charger le registre via son schéma, refuser les profils
inconnus ou non conformes et journaliser l'identifiant de profil, sa version et
la corrélation de requête. Une demande d'outil ou d'écriture n'est jamais
autorisée par le texte produit par le modèle.

