# Proposition d'évaluation — CORE-30M

Statut : **proposition non approuvée**. Ce document ne lance ni entraînement,
ni génération de masse, ni promotion de checkpoint. Il définit les preuves à
obtenir avant d'exposer CORE-30M au-delà d'un test expérimental.

## Objectif

CORE-30M sert de lignée d'apprentissage adaptée au volume de corpus actuellement
disponible. Une perte d'entraînement finie ou descendante démontre seulement la
stabilité numérique. Elle ne démontre ni français lisible, ni aptitude au code,
ni sûreté d'un assistant.

## Entrées figées d'une évaluation

Chaque rapport doit lier explicitement : configuration du modèle, checkpoint,
tokenizer, manifeste de corpus, split d'évaluation, code d'inférence, graine et
limites de génération par leurs SHA-256. Un changement de l'un de ces artefacts
crée une nouvelle évaluation ; les résultats ne sont pas transférables.

Le split d'évaluation est distinct de l'entraînement. Il ne contient pas de
conversation privée, de RAW non validé, de secret ni de réponse générée par le
modèle évalué.

## Trois niveaux de preuve

### E0 — intégrité mécanique

- le checkpoint est chargé offline avec les mêmes configuration et tokenizer ;
- la génération est bornée, UTF-8 valide et reproductible pour une même graine ;
- le même checkpoint est restauré depuis le stockage durable avec SHA-256
  identique ;
- tout écart d'empreinte, sortie non finie ou dépassement de limite échoue.

E0 autorise seulement la mention **CORE-30M expérimental**. Il n'autorise pas
un usage quotidien ni une promotion de moteur par défaut.

### E1 — lisibilité bilingue et technique

Le jeu candidat comporte au minimum 50 prompts expurgés, équilibrés entre
français et anglais, répartis entre explication courte, résumé de contrainte,
programmation et administration. Les réponses sont évaluées à l'aveugle par le
propriétaire sur quatre critères séparés : lisibilité, pertinence, respect de la
langue demandée et absence d'invention d'action exécutée.

Chaque réponse reçoit `accept`, `reject` ou `abstain`, avec une raison courte.
Un résultat n'est utilisable que si toutes les entrées et toutes les décisions
sont présentes ; `abstain` ne devient jamais `accept` implicitement.

Les seuils de passage et la taille finale du jeu restent à approuver par le
propriétaire. Tant qu'ils ne le sont pas, E1 produit une observation, jamais un
verdict de qualité.

### Résultat enregistré — 2026-09-09

Le checkpoint final du pilote pré-entraîné a été soumis à E1 avec le contrat de
corpus, tokenizer et préflight correspondant. Le runtime a refusé une sortie
répétitive pendant le garde E0 ; aucun paquet de réponses ni modèle de revue E1
n'a donc été créé. Ce résultat interdit de présenter cette lignée comme un chat
ou assistant de programmation utilisable. Il ne justifie ni un contournement du+garde ni une nouvelle estimation de qualité : les prochaines données doivent
être des paires instruction-réponse assainies et des tâches de code validées par
des tests externes.

### E2 — code vérifiable de l'extérieur

Les tâches de code décrivent une fonction, ses entrées et des tests attendus.
Pour chaque prompt, plusieurs candidats sont exécutés dans un bac à sable sans
réseau, sans accès aux données du projet, avec limites CPU, mémoire, disque et
durée. Seul le résultat des tests décide `accept` ou `reject` ; le modèle ne
juge jamais sa propre sortie.

Le rapport conserve le SHA-256 du prompt, du test, de la sortie et du résultat,
mais pas de secret ou de contenu privé. Une sortie rejetée ne rejoint ni corpus
d'entraînement ni file d'apprentissage.

## Règles de décision

1. BOOTSTRAP reste le défaut tant qu'E0, E1 et E2 ne sont pas approuvés et
   reproduits sur une lignée donnée.
2. Un score de perte, un débit ou un checkpoint ne remplace aucun niveau.
3. Une régression de sûreté, une répétition excessive ou une sortie qui prétend
   avoir exécuté une action provoque un échec de la lignée, même si les autres
   métriques sont bonnes.
4. Les seuils, le jeu de prompts et toute transition vers un moteur utilisable
   sont une décision explicite du propriétaire, versionnée séparément.

## Exécution E1 reproductible

`tools/run_core_language_evaluation.py` charge uniquement un checkpoint dont le
contrat est accepté par le runtime CPU local. Il produit un nouveau répertoire
atomique contenant les 50 réponses bornées, un reçu qui lie les empreintes du
checkpoint, de la configuration, du tokenizer, du manifeste et du préflight,
ainsi qu'un modèle de revue propriétaire séparé. Une destination existante est
refusée : une évaluation précédente reste donc inchangée. L'outil ne lance aucun
entraînement et ne déduit aucun verdict de qualité.

Le propriétaire remplit ensuite explicitement `accept`, `reject` ou `abstain`
dans une copie du modèle de revue. E2 ne démarre qu'après une spécification du
bac à sable et des tests de code approuvés.
