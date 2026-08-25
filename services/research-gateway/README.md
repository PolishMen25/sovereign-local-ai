# Research Gateway

Service provisoire de la zone Internet/DMZ chargé des appels aux fournisseurs externes. Il gérera, si cette architecture est validée, clés API, budgets, quotas, délais, erreurs et journal d'appel, puis remettra un paquet conforme au collecteur.

Il ne doit jamais recevoir automatiquement un contexte interne brut. Toute demande sortante doit passer par une politique de déclassification/anonymisation et, selon sa classe, une approbation humaine.

