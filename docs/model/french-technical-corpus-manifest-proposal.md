# Proposition de manifeste — corpus français-technique

Statut : **candidat non approuvé**. Les dix archives du catalogue ont été
acquises en `RAW` le 2026-09-08 ; aucune n'a été promue dans `VALIDATED`.

## Mesure RAW 2026-09-08

- 10 archives GitHub figées, 169 470 351 octets RAW et SHA-256 par paquet ;
- 75 228 fichiers texte admissibles et 48 256 fichiers exclus ;
- 97 396 860 tokens estimés, dont 406 893 français (0,417768 %) ;
- ce résultat dépasse le pilote de 10 M tokens : aucun entraînement ni
  promotion ne peut partir avant un sous-échantillonnage approuvé ;
- reçu durable :
  `/volume1/sovereign-ai-secure/raw/corpus-v1-acquisition-20260908.receipt.json`.

## Cible

Ce futur corpus vise le français conversationnel technique : administration
système, réseau, programmation et documentation d'outils. Il ne remplace pas
le corpus anglais technique initial lié au tokenizer `candidate_core` actuel.

## Contrat proposé pour chaque paquet

Avant toute promotion, chaque paquet doit disposer dans un manifeste signé
par le propriétaire des champs suivants :

- identifiant stable, URL exacte et date de récupération ;
- langue attendue, type (`documentation` ou `code`) et version source ;
- licence explicite, compatible avec l'entraînement local et vérifiée
  manuellement ;
- empreinte SHA-256 des octets RAW et de chaque dérivé ;
- décision de validation, auteur, date et motif de rejet éventuel ;
- résultats du filtrage des secrets, données personnelles et contenu hors
  périmètre.

## Périmètre admissible proposé

1. Documentation officielle française dont la licence autorise explicitement
   la réutilisation envisagée.
2. Dépôts de code publiés sous licence permissive explicite (MIT, BSD ou
   Apache-2.0), avec licence conservée et version figée.

Sont exclus par défaut : forums, conversations, tickets privés, dépôts sans
licence, documentation dont les droits sont ambigus, données personnelles et
secrets. Aucun paquet ne passe de `RAW` à `VALIDATED` automatiquement.

## Gate d'approbation

Le propriétaire doit approuver un manifeste qui nomme les sources exactes,
leurs licences, versions et empreintes attendues avant toute acquisition.
L'entraînement CORE ne consomme que les paquets `VALIDATED` liés par ce
manifeste ; les conversations et la mémoire restent hors des poids.
