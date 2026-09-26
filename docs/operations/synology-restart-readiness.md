# Préparer le Synology avant de relancer le calcul

**Statut : procédure PROVISOIRE, lecture seule.** Cette page décrit comment
vérifier, depuis le NAS puis depuis l'hôte de calcul, que le stockage durable
est prêt avant de reprendre un calcul. Elle ne décrit pas l'état du NAS : le
constat détaillé, la posture de sécurité et la liste des actions du
propriétaire restent dans l'inventaire interne, hors Git (D-004, D-025).

Le NAS stocke et ne calcule pas (D-005). Le calcul actif reste local à l'hôte
de calcul ; le NAS porte les copies durables ([stockage](../../infra/storage/README.md)).

## 1. Le contrôleur

### 2.1 Le contrôleur

`tools/check_synology_readiness.py` est un outil en lecture seule qui n'utilise
que la bibliothèque standard. Il est compatible avec Python 3.8 et ses
versions ultérieures, et il est testé par
`tests/test_check_synology_readiness.py`. Voici ce qu'il fait et ce qu'il
s'interdit :

- il n'écrit jamais : il ne crée ni fichier, ni dossier, ni fichier `.pyc`
  lorsqu'il est lu sur l'entrée standard ;
- il ne suit aucun lien symbolique ; un lien qui sort de la racine est refusé
  et signalé ;
- il ne traverse aucun autre système de fichiers et saute les métadonnées
  Synology (`@eaDir`, `#recycle` et `#snapshot`) ;
- il ne lit le contenu d'un fichier qu'avec `--verify-sha256`, et seulement
  pour les manifestes de sauvegarde, les fichiers `*.sha256` (4 Kio au plus)
  et les artefacts qu'ils désignent ;
- son parcours est borné en nombre d'entrées, en profondeur, en durée (y
  compris à l'intérieur d'un grand dossier) et en octets hachés ;
- sa sortie est un unique objet JSON sur la sortie standard. Elle contient des
  étiquettes et des agrégats (nombres, octets, dates UTC), jamais de chemin,
  de nom de fichier, de compte ou d'hôte. Un dossier attendu dont le nom n'est
  pas public est remplacé par `folder_<n>`.

| Option | Défaut | Rôle |
| --- | --- | --- |
| `--share-root` | obligatoire | Racine du partage ; elle n'est jamais affichée et ne doit pas être un lien. |
| `--expected-folders` | `raw,validated,models,backups` | Dossiers de premier niveau exigés, 16 au plus. |
| `--backup-folder` | `backups` | Dossier dont on mesure la fraîcheur ; il doit figurer parmi les dossiers attendus. |
| `--no-backup-check` | inactif | Saute le contrôle des sauvegardes, pour un partage qui n'en contient pas (partage chiffré, section 2). |
| `--access` | `read-write` | Accès exigé du compte qui exécute : `exists`, `read` ou `read-write`. `exists` vérifie seulement la présence des dossiers et l'espace libre, sans les parcourir : un dossier présent mais fermé au compte vaut `present`. Ce mode refuse `--verify-sha256` et saute les sauvegardes. |
| `--min-free-gib` | `100` | Espace libre minimal du volume vu par le client, entre 0 et 1 048 576. |
| `--max-backup-age-hours` | `24` | Âge maximal de la sauvegarde la plus récente, pour chaque type, entre 1 et 87 600. |
| `--verify-sha256` | inactif | Vérifie d'abord les 3 manifestes de sauvegarde les plus récents de chaque type, puis les fichiers `<artefact>.sha256`. |
| `--max-hash-files` / `--max-hash-gib` | `64` / `32` | Budget de vérification. |
| `--max-entries` / `--max-depth` | `200000` / `16` | Bornes du parcours. |
| `--time-budget-seconds` | `240` | Durée maximale. Au-delà, le résultat est au mieux `attention`. |
| `--require-mount-point` | inactif | Refuse une racine qui n'est pas un point de montage ; à utiliser côté calcul. |

Un fichier `<artefact>.sha256` contient une seule ligne : l'empreinte
hexadécimale, éventuellement suivie du nom exact de l'artefact (format
`sha256sum`). Aucun outil du dépôt n'écrit aujourd'hui de tel fichier : en
pratique, `--verify-sha256` ne vérifie que les manifestes de sauvegarde ; les
autres artefacts se vérifient contre leur référence versionnée dans le dépôt
(locks et reçus de promotion) avec `sha256sum`. Seuls les artefacts reconnus
(`memory-*.sqlite3` et `knowledge-index-*.sqlite3`) comptent comme sauvegarde :
un manifeste seul ou un fichier étranger ne suffit jamais.

Les codes de sortie sont les suivants :

| Code | `overall` | Signification |
| --- | --- | --- |
| 0 | `ready` | Aucun point bloquant ni à examiner. |
| 1 | `attention` | Aucun blocage, mais au moins un point à examiner avant de reprendre. |
| 2 | `not_ready` | Blocage, ou erreur interne traitée en échec fermé. |
| 64 | aucun JSON | Ligne de commande invalide, ou aide demandée (`--help`, affichée sur la sortie d'erreur) ; la valeur refusée n'est jamais recopiée. |

Seul le code 0 accompagné d'un JSON dont `overall` vaut `ready` signifie
« prêt ». Clés toujours présentes : `schema_version`, `observed_at`,
`overall`, `reasons` et `checks.<contrôle>.status`. Les autres champs d'un
contrôle `skipped`, ou bloqué faute d'accès, peuvent manquer ou valoir `null`,
et le rapport d'erreur interne n'a ni `limits` ni contrôles détaillés.


## 2. Commandes

Depuis le poste d'administration, à la racine du dépôt. Le script est lu sur
l'entrée standard : rien n'est copié sur le NAS.

Contrôle de présence, possible même si le compte d'inspection ne peut pas lire
les dossiers de données : il vérifie que le partage est monté et déverrouillé,
que les dossiers attendus existent et que l'espace libre suffit.

```bash
ssh -o BatchMode=yes <alias-NAS> "python3 - --share-root <racine-du-partage> --access exists"   < tools/check_synology_readiness.py
echo "code de sortie : $?"
```

Partage chiffré sans sauvegardes : détecte un partage resté verrouillé après
un redémarrage du NAS.

```bash
ssh -o BatchMode=yes <alias-NAS>   "python3 - --share-root <racine-du-partage-chiffré> --access read --no-backup-check --expected-folders raw,validated,models"   < tools/check_synology_readiness.py
```

Contrôle complet, avec un compte qui peut lire les dossiers. Après un arrêt
prolongé du calcul, fixer `--max-backup-age-hours` au nombre d'heures écoulées
depuis la dernière sauvegarde connue, plus une marge de 24 heures : une
sauvegarde ancienne est alors attendue et ne bloque pas la relance.

```bash
ssh -o BatchMode=yes <alias-NAS>   "python3 - --share-root <racine-du-partage> --access read --verify-sha256 --max-backup-age-hours <heures>"   < tools/check_synology_readiness.py
```

Depuis l'hôte de calcul, une fois le montage actif, avec le compte de service :

```bash
python3 -B tools/check_synology_readiness.py --share-root <point-de-montage>   --require-mount-point --access read-write --verify-sha256 --max-backup-age-hours <heures>
```

## 3. Ordre de relance

1. **Avant la mise sous tension du calcul** : contrôle de présence sur le NAS,
   code 0 attendu. Un partage chiffré verrouillé se déverrouille dans DSM par
   le propriétaire ; ne jamais placer la clé sur l'hôte de calcul.
2. **Démarrage de l'hôte de calcul** : vérifier que l'unité de montage est
   active, en SMB 3.1.1 chiffré (`seal`), avant les conteneurs.
3. **Contrôle complet depuis l'hôte de calcul** avec `--require-mount-point`.
   Tout `not_ready` bloque la reprise ; un `attention` s'examine raison par
   raison.
4. **Avant de reprendre un entraînement** : ne jamais interrompre un calcul en
   cours, recharger le dernier checkpoint durable dont l'empreinte SHA-256
   concorde avec sa référence, ne jamais écraser une destination existante et
   conserver la source (règles de la [reprise Claude Code](../project/claude-code-handoff.md)).
5. **Première sauvegarde après relance** : relancer le contrôle complet avec
   `--max-backup-age-hours 24` ; le code 0 confirme que la chaîne de
   sauvegarde est repartie.
