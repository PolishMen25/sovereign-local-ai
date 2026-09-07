# Proposition de manifeste — corpus français-technique

Statut : **brouillon non exécutable**. Aucune source listée ici n'a été
téléchargée, acquise, copiée dans `RAW` ou promue dans `VALIDATED`.

## Cible

Ce futur corpus vise le français conversationnel technique : administration
système, réseau, programmation et documentation d'outils. Il ne remplace pas
le corpus anglais technique initial lié au tokenizer `candidate_core` actuel.

## Contrat proposé pour chaque paquet

Avant toute acquisition, chaque paquet doit disposer dans un manifeste signé
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
