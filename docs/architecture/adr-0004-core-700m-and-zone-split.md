# ADR-0004 — CORE-700M et séparation du sas réseau

- **Statut : APPROUVÉ**
- **Date : 2026-09-01**
- **Décideur : propriétaire du projet**

## Contexte

Le chat BOOTSTRAP temporaire a besoin d'un accès privé par LAN et tailnet,
alors qu'IA-CORE ne doit posséder aucune route Internet. Le propriétaire vise
désormais un assistant général créé dans le projet et choisit un candidat plus
grand que CORE-80M. Les conversations privées doivent rester dans la mémoire et
le RAG, sans être incorporées automatiquement aux poids.

## Décision

1. `CORE-700M` devient le candidat principal. Sa définition machine contient
   exactement **691 160 320 paramètres entraînables** : vocabulaire 32 000,
   dimension 1 280, 32 blocs, 20 têtes de dimension 64, MLP SwiGLU 3 584,
   RoPE, RMSNorm, embeddings liés et aucun biais. Le contexte candidat est
   2 048 tokens.
2. CORE-MINI reste le gate logiciel. CORE-80M reste une référence historique et
   n'est plus la cible d'entraînement long.
3. Le sas d'interface et IA-CORE sont deux invités non privilégiés distincts.
   Le sas porte l'interface, l'identité locale et l'accès tailnet. IA-CORE ne
   possède aucune passerelle ni DNS externe.
4. Depuis IA-CORE, le pare-feu n'autorise que le stockage interne explicitement
   approuvé et les réponses à l'API d'inférence appelée par le sas. Toute autre
   sortie est refusée et testée après redémarrage.
5. Un petit moteur d'embeddings RAG pré-entraîné est autorisé s'il est acquis
   dans la zone externe, figé par empreinte et licence, puis exécuté hors ligne.
   Ses poids ne font pas partie de CORE.
6. Le corpus de CORE est limité aux sources réutilisables dont la licence et la
   provenance sont vérifiées. Les données privées restent dans le RAG et la
   mémoire jusqu'à suppression demandée par le propriétaire.

## Conséquences

- l'interface peut rester disponible sur le LAN et le tailnet sans accorder une
  route Internet à IA-CORE ;
- les identités de stockage du Collector, du sas et de CORE sont séparées ;
- le calcul exact et les tests doivent évoluer avec la configuration 700M ;
- aucun entraînement long n'est autorisé avant benchmark CPU/NUMA reproductible,
  approbation du corpus et du tokenizer, seuils d'arrêt et test de reprise ;
- aucune durée ni qualité d'assistant général n'est promise avant ces mesures ;
- BOOTSTRAP reste explicitement nommé tant que CORE-700M n'a pas franchi les
  évaluations de promotion.

