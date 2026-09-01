# Runtime d’inférence local

`runtime.py` fixe la frontière CPU-only du futur moteur CORE. Il expose un
statut local et refuse actuellement **toute** génération. Sans poids, l'état est
`awaiting_local_weights`; si un fichier est détecté, l'état devient
`weights_detected_runtime_disabled`, car aucun chargeur, tokenizer ni décodeur
autorégressif n'est encore activé. Aucun fallback distant, GPU ou téléchargement
automatique n’est permis.

`model.py` contient désormais la définition commune du decoder CORE utilisée
par le harness d'entraînement et destinée au futur runtime. Elle préserve les
noms et formes des poids existants, exige les embeddings liés, vérifie le
comptage et refuse un build CUDA/ROCm ou un runtime CUDA actif.

`configuration.py` lit la configuration CORE-MINI une seule fois, dans une
copie d'octets bornée, puis applique un JSON strict, l'architecture et le
comptage exacts avant de calculer le SHA-256 sur ces mêmes octets. `cli.py`
fournit aux outils publics un parseur qui conserve l'aide standard sans recopier
un chemin fourni dans les erreurs.

`tokenizer.py` charge et valide le format Byte-BPE expérimental `0.2.0`. Il
partage avec l'outil d'apprentissage la normalisation NFC et l'application des
fusions ordonnées. Son état validé est immuable et ses entrées sont bornées.
Cette capacité permet de tester un aller-retour texte/tokens ; elle n'autorise
pas encore le chargement de poids linguistiques ni la génération.

`checkpoint.py` fournit les primitives CPU strictes partagées par le harness et
le vérificateur offline. Avant une reprise, il compare les clés, formes, types,
layouts et placement CPU des tenseurs du modèle, puis la structure, l'ordre des
paramètres, les options et l'état complet d'AdamW. Ce contrôle de compatibilité
refuse aussi les strides, tailles ou décalages de stockage et alias de tenseurs
AdamW inattendus. Il ne transforme pas un checkpoint synthétique en poids
linguistiques et n'active pas le runtime. Il est couvert par les tests locaux,
mais sa compatibilité avec le checkpoint historique reste à confirmer sur
Linux.

Le candidat `CORE-80M` reste une configuration d’architecture, pas un modèle
prêt à charger. L’implémentation complète attend le tokenizer, le corpus, des
poids linguistiques validés, la génération, le mini-benchmark et la politique
de précision définis aux gates correspondants. Le champ déclaratif
`network=disabled` décrit le contrat du runtime ; il ne remplace pas la preuve
de segmentation réseau exigée par le gate d'architecture.
