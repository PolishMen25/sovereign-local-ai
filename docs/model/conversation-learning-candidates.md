# Candidats d’apprentissage issus des conversations

Statut : **actif pour la mise en file et l’export candidat ; inactif pour
l’entraînement automatique**.

Les messages `user` et `assistant` enregistrés par la mémoire privée sont
assainis avant stockage puis placés dans une file locale. L’exporteur opérateur
`tools/export_conversation_learning_candidates.py` ne retient que les paires
complètes utilisateur/réponse et produit un nouveau répertoire contenant :

- `learning-candidates.jsonl`, avec le texte assaini et des identifiants
  pseudonymisés ;
- `manifest.candidate.json`, avec l’empreinte SHA-256 relue après écriture, les
  compteurs et les exclusions sans recopier les conversations.

Une réponse isolée, une question sans réponse et tout message `system` ou
`tool` sont exclus. Une incohérence entre le contenu assaini et son empreinte
stockée bloque l’export. Une destination existante est toujours refusée afin de
ne jamais écraser silencieusement un paquet antérieur.

Le manifeste porte `pending_owner_approval` et `automatic_promotion=false`.
L’export ne copie rien dans `RAW` ou `VALIDATED`, ne modifie aucun checkpoint et
ne déclenche aucun entraînement. Pour devenir une entrée d’entraînement, un
paquet devra suivre la même chaîne que le corpus externe : revue, manifeste
figé, empreintes vérifiées, approbation du propriétaire puis gate bloquant.

La suppression d’une conversation retire ses messages de la file SQLite. Tout
paquet candidat antérieur à cette suppression doit être régénéré et réapprouvé
avant usage ; son empreinte précédente ne peut pas être réutilisée.
