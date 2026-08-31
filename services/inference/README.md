# Runtime d’inférence local

`runtime.py` fixe la frontière CPU-only du futur moteur CORE. Il expose un
statut local et refuse toute génération tant que les poids n’ont pas été
produits, vérifiés et installés. Aucun fallback distant, GPU ou téléchargement
automatique n’est permis.

Le candidat `CORE-80M` reste une configuration d’architecture, pas un modèle
prêt à charger. L’implémentation complète attend le tokenizer, le corpus, le
mini-benchmark et la politique de précision définis aux gates correspondants.
