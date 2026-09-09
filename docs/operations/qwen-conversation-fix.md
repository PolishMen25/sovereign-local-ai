# Correction du contexte Qwen Coder

La passerelle transmet désormais à Qwen les 20 derniers messages déjà lus
dans la mémoire, dans leur ordre, ainsi que les références locales préparées
par la recherche lexicale. Auparavant seul le dernier message était transmis,
alors que des citations pouvaient être affichées dans la réponse.

La consigne système identifie Qwen Coder et ne lui attribue aucun outil
d'exécution. BOOTSTRAP conserve son comportement. Le client refuse les
réponses vides, les historiques malformés et les réponses de santé non objet.

## Vérification

- Suite locale : 286 tests, un saut attendu, aucun échec.
- Déploiement ciblé des deux fichiers Python, copies précédentes conservées,
  octets relus après écriture ; passerelle active après redémarrage.
- Appel réel depuis la passerelle : un historique synthétique donne le nom
  `count_stars` et une référence locale indique Python 3.11. La question
  suivante ne répète aucune de ces valeurs ; Qwen restitue les deux en
  14,28 secondes. Cette mesure ponctuelle n'est pas un benchmark.

Le test réel appelle le client déployé, pas une session propriétaire dans le
navigateur. Les tests du client vérifient la conservation des rôles, références
et tours. Ils ne prouvent pas une restauration Synology ni la qualité générale
du moteur. Le contexte serveur reste limité : un historique trop volumineux
peut encore être refusé par le moteur. Aucun découpage silencieux supplémentaire
ni augmentation du contexte serveur n'est introduit par cette correction.
