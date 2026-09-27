"""D-025 : la documentation publique ne republie pas la fiche CPU exacte du ML350.

D-003 est SUPERSEDED par D-025 : le dépôt public conserve seulement le
caractère bi-socket NUMA et CPU-only du ML350, et toute valeur exacte publiée
doit être explicitement autorisée par une entrée du registre. Ce test refuse,
dans README.md et docs/**/*.md, tout marqueur de fiche CPU qu'aucune exception
citant une décision D-xxx active et rattachée à D-025 n'autorise.

Aucune valeur réelle, ni en clair ni sous forme d'empreinte, ne figure dans ce
fichier : chaque marqueur est reconnu par une forme générique, quelles que
soient la valeur et la machine décrite.

- Modèle : famille E5 à quatre chiffres, suffixe A et suffixe de génération
  accolés ou non, préfixe multiplicateur.
- Cœurs et threads : paire « nC/nT » ; décompte formulé comme un inventaire
  (cœurs, cores, « n-core », CPU ou processeurs logiques ou physiques, threads
  matériels, logiques ou par socket) ; libellé suivi d'un nombre (« Cœurs : n »,
  lignes de type lscpu sauf « Socket(s) ») ; décompte nu (threads, CPU, vCPU,
  processeurs) dans un paragraphe qui nomme le ML350, un hôte, un nœud de
  calcul, lscpu ou nproc.
- Mémoire : quantité en Go, Gio ou GiB qualifiée de visible.

Un décompte nu sans contexte matériel, par exemple « n threads de calcul »,
reste admis : c'est un réglage d'exécution. Écrit dans le même paragraphe que
le nom de la machine, il est refusé par prudence ; le reformuler sans valeur
exacte ou le faire autoriser par une décision. Aucune comparaison avec une
valeur précise n'est employée : une empreinte d'un petit entier se retrouve
par énumération et republierait la valeur.

Les fixtures emploient des valeurs synthétiques assemblées à l'exécution, et
un test vérifie que ce fichier ne contient aucune forme refusée. Les messages
d'échec donnent le fichier, la ligne et l'identifiant du marqueur, jamais la
valeur trouvée.

Périmètre : dans un dépôt Git, seuls les fichiers suivis (``git ls-files``)
sont analysés, car eux seuls peuvent être publiés ; un inventaire privé non
suivi placé sous docs/ n'est donc pas examiné et ne doit jamais être ajouté à
l'index. Hors dépôt Git (archive, fixtures), si Git est indisponible ou si la
liste suivie est vide, le test parcourt le système de fichiers, ce qui est
plus strict. Un ensemble vide de documents est refusé, et le test principal
exige que README.md et le registre des décisions aient été lus.

Hors périmètre : les fichiers de configuration (par exemple configs/runtime),
que D-025 ne couvre pas ; leur sort relève du propriétaire.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = PROJECT_ROOT / "docs" / "project" / "decisions.md"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_GIT_LISTING_BYTES = 1024 * 1024
GIT_TIMEOUT_SECONDS = 30

# Exceptions explicites à D-025. Chaque entrée nomme un document public
# (chemin POSIX relatif à la racine), un identifiant de ``MARKER_IDS`` et
# l'entrée D-xxx active du registre qui autorise, en citant D-025, la
# publication de cette valeur exacte dans ce document. La liste reste vide tant
# qu'aucune décision n'autorise de valeur exacte.
ALLOWED_PUBLICATIONS: tuple[dict[str, str], ...] = ()

MARKER_IDS = ("ml350-cpu-model", "ml350-core-thread-count", "ml350-visible-ram")
REDACTION_DECISION = "D-025"

_ALLOWLIST_KEYS = {"path", "marker", "decision"}
_DECISION_ID = re.compile(r"^D-\d{3}$")
_REGISTER_ROW = re.compile(r"^\|\s*(D-\d{3})\s*\|(.*)$")
_CITES_REDACTION_DECISION = re.compile(rf"(?<![\w-]){REDACTION_DECISION}(?!\d)")
_HYPHENS = "\\-\u2010\u2011\u2012\u2013\u2014\u2015"
_MULTIPLIER = r"(?:\d{1,2}\s*[x\u00d7]\s*)?"
# Un nombre qui n'est pas collé à un mot, sauf à un multiplicateur « 2x ».
_COUNT = r"(?:(?<=[x\u00d7])|(?<![\w.,]))\d{1,4}"
_JOIN = rf"[\s{_HYPHENS}]*"
_COEUR = r"c(?:oe|\u0153)urs?"
# « cores » reste sensible à la casse pour épargner le nom de modèle CORE.
_CORE = r"(?-i:[Cc]ores?|CORES)"
_INVENTORY_NOUN = (
    rf"(?:{_COEUR}|{_CORE}"
    r"|(?:cpus?|processeurs?|processors?)\s+(?:logiques?|physiques?)"
    r"|(?:logical|physical)\s+(?:cpus?|cores?|processors?)"
    rf"|threads?\s+(?:mat[e\u00e9]riels?|logiques?|physiques?|(?:par|per)\s+(?:socket|{_COEUR}|core))"
    r"|hardware\s+threads?)"
)

# Formes génériques : aucune valeur réelle. Les chiffres sont délimités par des
# assertions sur les caractères voisins plutôt que par \b, afin qu'un suffixe
# de génération accolé ou un préfixe multiplicateur soient aussi détectés ; la
# famille de modèle refuse un voisin hexadécimal, sauf un suffixe A isolé, pour
# épargner les empreintes.
_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ml350-cpu-model",
        re.compile(
            rf"(?<![0-9A-Za-z]){_MULTIPLIER}E5[\s{_HYPHENS}]*\d{{4}}"
            r"(?:A(?=\s*v\d)|A(?![0-9A-Za-z])|(?![0-9A-Fa-f]))",
            re.IGNORECASE,
        ),
    ),
    (
        "ml350-core-thread-count",
        re.compile(r"(?<!\d)\d{1,4}\s*C\s*/\s*\d{1,4}\s*T(?:hreads?)?(?![0-9A-Za-z])", re.IGNORECASE),
    ),
    (
        "ml350-core-thread-count",
        re.compile(rf"{_COUNT}{_JOIN}{_INVENTORY_NOUN}(?![\w-])", re.IGNORECASE),
    ),
    (
        "ml350-core-thread-count",
        re.compile(
            rf"(?<!\w){_INVENTORY_NOUN}(?:\s+(?:par|per)\s+(?:socket|{_COEUR}|core))?\s*:\s*\d",
            re.IGNORECASE,
        ),
    ),
    (
        "ml350-core-thread-count",
        re.compile(
            r"(?<!\w)(?:cpu|core|c(?:oe|\u0153)ur|thread|processeur)\(s\)[^:\n]{0,32}:\s*\d", re.IGNORECASE
        ),
    ),
    ("ml350-visible-ram", re.compile(r"(?<![A-Za-z])Gi?[oB]\s+visibles?(?!\w)", re.IGNORECASE)),
)

# Décompte nu : refusé seulement dans un paragraphe qui nomme une machine.
_BARE_COUNT = re.compile(
    rf"{_COUNT}{_JOIN}(?:threads?|v?cpus?|processeurs?|processors?)(?![\w-])", re.IGNORECASE
)
_HOST_CONTEXT = re.compile(
    r"(?<!\w)(?:ML\s*350|h[o\u00f4]tes?|hosts?|n(?:oe|\u0153)uds?\s+de\s+calcul|lscpu|nproc)(?!\w)",
    re.IGNORECASE,
)
_PARAGRAPH = re.compile(r"(?:[^\n]*\S[^\n]*(?:\n|$))+")


def scan_text(text: str) -> list[tuple[int, str]]:
    """Return (line, marker id) for every forbidden marker in ``text``."""

    def line_of(offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    hits: set[tuple[int, str]] = set()
    for marker_id, pattern in _SHAPES:
        hits.update((match.start(), marker_id) for match in pattern.finditer(text))
    for paragraph in _PARAGRAPH.finditer(text):
        if _HOST_CONTEXT.search(paragraph.group()):
            hits.update(
                (paragraph.start() + match.start(), "ml350-core-thread-count")
                for match in _BARE_COUNT.finditer(paragraph.group())
            )
    return sorted((line_of(offset), marker_id) for offset, marker_id in hits)


def _is_public_document(relative: str) -> bool:
    return relative == "README.md" or (relative.startswith("docs/") and relative.endswith(".md"))


def _git_environment() -> dict[str, str]:
    # Un GIT_DIR ou GIT_INDEX_FILE hérité (crochet Git) désignerait un autre dépôt.
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def tracked_public_documents(root: Path) -> list[Path] | None:
    """List the tracked public documents, or None when Git cannot answer for ``root``."""

    if not (root / ".git").exists() or shutil.which("git") is None:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "README.md", "docs"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_environment(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    if len(completed.stdout) > MAX_GIT_LISTING_BYTES:
        raise ValueError(f"git listing exceeds {MAX_GIT_LISTING_BYTES} bytes")
    try:
        listing = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("git listing is not valid UTF-8") from error
    documents = [
        root / relative
        for relative in listing.split("\0")
        # Un fichier suivi mais absent de l'arbre de travail n'a rien à lire.
        if relative and _is_public_document(relative) and os.path.lexists(root / relative)
    ]
    return sorted(documents) or None


def _walk_public_documents(root: Path) -> list[Path]:
    documents = [root / "README.md"] if os.path.lexists(root / "README.md") else []
    docs = root / "docs"
    if docs.is_dir():
        documents.extend(docs.rglob("*.md"))
    return sorted(documents)


def public_documents(root: Path) -> list[Path]:
    """Return README.md and docs/**/*.md: tracked files in a Git checkout, else a filesystem walk."""

    tracked = tracked_public_documents(root)
    return tracked if tracked is not None else _walk_public_documents(root)


def _read_document(path: Path, *, max_bytes: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"public document must be a regular file: {path.name}")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"public document exceeds {max_bytes} bytes: {path.name}")
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"public document is not valid UTF-8: {path.name}") from error


def scan_public_documents(root: Path, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> list[tuple[str, int, str]]:
    """Return (relative path, line, marker id) for every forbidden marker found."""

    documents = public_documents(root)
    if not documents:
        # Ne rien lire ne prouve rien : refuser plutôt que conclure à l'absence.
        raise ValueError("no public document found to scan")
    findings: list[tuple[str, int, str]] = []
    for path in documents:
        text = _read_document(path, max_bytes=max_bytes)
        relative = path.relative_to(root).as_posix()
        findings.extend((relative, line, marker) for line, marker in scan_text(text))
    return sorted(findings)


def register_rows(decisions_path: Path) -> dict[str, str]:
    """Map each D-xxx identifier of the register to the rest of its table row."""

    rows: dict[str, str] = {}
    for line in decisions_path.read_text(encoding="utf-8").splitlines():
        match = _REGISTER_ROW.match(line.strip())
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def validate_allowlist(
    entries: tuple[dict[str, str], ...], *, root: Path, decisions: dict[str, str]
) -> set[tuple[str, str]]:
    """Refuse any exception that does not cite an active exception to D-025 or no longer applies."""

    allowed: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != _ALLOWLIST_KEYS:
            raise ValueError(f"allowlist[{index}] must have exactly the keys {sorted(_ALLOWLIST_KEYS)}")
        if not all(isinstance(entry[key], str) for key in _ALLOWLIST_KEYS):
            raise ValueError(f"allowlist[{index}] values must be strings")
        decision = entry["decision"]
        if not _DECISION_ID.fullmatch(decision):
            raise ValueError(f"allowlist[{index}] must cite a D-xxx decision")
        if decision not in decisions:
            raise ValueError(f"allowlist[{index}] cites a decision absent from the register")
        if "SUPERSEDED" in decisions[decision].upper():
            raise ValueError(f"allowlist[{index}] cites a superseded decision")
        if decision == REDACTION_DECISION:
            raise ValueError(f"allowlist[{index}] cites {REDACTION_DECISION} itself, which grants no exception")
        # Une décision active sans rapport (licence, stockage, rôle d'un serveur)
        # ne suffit pas : sa ligne du registre doit nommer D-025 pour y déroger.
        if not _CITES_REDACTION_DECISION.search(decisions[decision]):
            raise ValueError(f"allowlist[{index}] cites a decision that does not reference {REDACTION_DECISION}")
        if entry["marker"] not in MARKER_IDS:
            raise ValueError(f"allowlist[{index}] names an unknown marker")
        relative = entry["path"]
        if relative != "README.md" and not relative.startswith("docs/"):
            raise ValueError(f"allowlist[{index}] path is outside the public documents")
        if ".." in Path(relative).parts or Path(relative).is_absolute():
            raise ValueError(f"allowlist[{index}] path must stay inside the repository")
        document = root / relative
        if not document.is_file():
            raise ValueError(f"allowlist[{index}] path does not exist")
        text = _read_document(document, max_bytes=MAX_DOCUMENT_BYTES)
        if not any(marker == entry["marker"] for _line, marker in scan_text(text)):
            raise ValueError(f"allowlist[{index}] is stale: the marker is no longer present")
        allowed.add((relative, entry["marker"]))
    return allowed


# Valeurs synthétiques, jamais celles du ML350.
SYNTHETIC_MODEL = "E5-" + "1234"
SYNTHETIC_CORES = "12"
SYNTHETIC_THREADS = "24"


class PublicHardwareRedactionTests(unittest.TestCase):
    def write(self, root: Path, relative: str, text: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def git(self, root: Path, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_environment(),
            check=True,
        )

    def sheet_style_lines(self) -> dict[str, str]:
        """Rebuild, with synthetic values, the kind of wording D-025 forbids."""

        model, cores, threads = SYNTHETIC_MODEL, SYNTHETIC_CORES, SYNTHETIC_THREADS
        pair = f"{cores}C/{threads}T"
        ram = "G" + "io " + "visibles"
        return {
            "docs/project/decisions.md": f"| D-900 | Hôte synthétique : 2 x {model} v9, {pair}, ~64 {ram}. |\n",
            "docs/architecture/overview.md": f"- Hôte synthétique : {model}v9, 2x{pair}.\n",
            "docs/model/core-80m.md": f"L'hôte synthétique dispose de {cores} cœurs et de {threads} threads.\n",
            "README.md": f"Serveur synthétique : 2x{model}.\n",
        }

    def test_public_documents_do_not_republish_the_ml350_cpu_sheet(self) -> None:
        scanned = {path.relative_to(PROJECT_ROOT).as_posix() for path in public_documents(PROJECT_ROOT)}
        # Un ensemble vide ou tronqué ferait passer le test sans rien lire.
        self.assertLessEqual({"README.md", "docs/project/decisions.md"}, scanned)
        allowed = validate_allowlist(
            ALLOWED_PUBLICATIONS, root=PROJECT_ROOT, decisions=register_rows(DECISIONS_PATH)
        )
        findings = [
            finding for finding in scan_public_documents(PROJECT_ROOT)
            if (finding[0], finding[2]) not in allowed
        ]
        self.assertEqual(
            findings, [],
            "D-025 : valeur exacte du ML350 republiée sans autorisation (fichier, ligne, marqueur). "
            "Rédiger comme « bi-socket NUMA, CPU-only » ou citer dans ALLOWED_PUBLICATIONS "
            "une décision D-xxx qui déroge à D-025.",
        )

    def test_scanner_flags_a_sheet_style_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, text in self.sheet_style_lines().items():
                self.write(root, relative, text)
            findings = scan_public_documents(root)
        flagged = {(path, marker) for path, _line, marker in findings}
        self.assertEqual(
            flagged,
            {
                ("docs/project/decisions.md", "ml350-cpu-model"),
                ("docs/project/decisions.md", "ml350-core-thread-count"),
                ("docs/project/decisions.md", "ml350-visible-ram"),
                ("docs/architecture/overview.md", "ml350-cpu-model"),
                ("docs/architecture/overview.md", "ml350-core-thread-count"),
                ("docs/model/core-80m.md", "ml350-core-thread-count"),
                ("README.md", "ml350-cpu-model"),
            },
        )
        self.assertEqual(sum(1 for f in findings if f[0] == "docs/model/core-80m.md"), 2)

    def test_attached_suffixes_multipliers_and_count_spellings_are_found(self) -> None:
        model, n = SYNTHETIC_MODEL, SYNTHETIC_CORES
        cases = {
            model + "v9": "ml350-cpu-model",
            "2x" + model: "ml350-cpu-model",
            "2 \u00d7 E5\u2011" + "1234 v9": "ml350-cpu-model",
            f"2 x {model}A v9": "ml350-cpu-model",
            f"{model}Av9": "ml350-cpu-model",
            f"{model}A, bi-socket": "ml350-cpu-model",
            "2x" + "6C/" + "12T": "ml350-core-thread-count",
            f"6 C / {SYNTHETIC_THREADS} threads": "ml350-core-thread-count",
            f"{n} CPU logiques": "ml350-core-thread-count",
            f"{n} cores": "ml350-core-thread-count",
            f"{n} CORES": "ml350-core-thread-count",
            f"{n}-core": "ml350-core-thread-count",
            f"{n}\u2011core": "ml350-core-thread-count",
            f"{n} logical CPUs": "ml350-core-thread-count",
            f"{n} physical cores": "ml350-core-thread-count",
            f"{n} threads matériels": "ml350-core-thread-count",
            f"{n} threads par socket": "ml350-core-thread-count",
            f"2x{n} cœurs": "ml350-core-thread-count",
            f"{n} coeurs": "ml350-core-thread-count",
            f"00{n} processeurs logiques": "ml350-core-thread-count",
            f"Cœurs : {n}": "ml350-core-thread-count",
            f"Logical CPUs: {n}": "ml350-core-thread-count",
            f"Cœurs par socket\u00a0: {n}": "ml350-core-thread-count",
            f"CPU(s): {n}": "ml350-core-thread-count",
            f"Cœur(s) par socket : {n}": "ml350-core-thread-count",
            f"Le ML350 expose {n} threads": "ml350-core-thread-count",
            f"Hôte synthétique : {n} vCPU": "ml350-core-thread-count",
            f"Sur le nœud de calcul, {n}\u00a0threads": "ml350-core-thread-count",
            "64 Go " + "visibles": "ml350-visible-ram",
            "64Gio " + "visible": "ml350-visible-ram",
            "64 GiB " + "visible": "ml350-visible-ram",
        }
        for text, marker in cases.items():
            with self.subTest(text=text):
                self.assertEqual(scan_text(text + "\n"), [(1, marker)])

    def test_detection_does_not_depend_on_the_value(self) -> None:
        for value in ("1", "7", "16", "96", "1024"):
            for template in ("{} cœurs", "{}-core", "Cœurs : {}", "{}C/{}T", "Hôte : {} threads"):
                text = template.format(value, value)
                with self.subTest(text=text):
                    self.assertEqual(scan_text(text + "\n"), [(1, "ml350-core-thread-count")])

    def test_benign_counts_names_and_digests_are_not_flagged(self) -> None:
        few = "8"  # réglage d'exécution synthétique
        benign = (
            "12 CORE-MINI",
            "run E1 CORE-30M",
            "CORE : 80M paramètres",
            f"{few} threads de calcul",
            f"Le benchmark CORE-MINI utilise {few} threads, batch 1.",
            f"ML350 Gen9 : CPU-only, bi-socket et NUMA.\n\nLe benchmark utilise {few} threads de calcul.",
            "HPE ML350 Gen9 CPU-only",
            "ML350 Gen9 cores NUMA",
            "0,12 threads",
            "8 000 CPU-secondes",
            "[ADR-0004](adr-0004-core-700m.md)",
            "Socket(s): 2",
            "sha256:" + "e5" + "1234" + "abcdef",
            "sha256:" + "e5" + "1234" + "a" + "bcdef",
            "E5-" + "12345",
            "bi-socket NUMA, CPU-only",
        )
        for text in benign:
            with self.subTest(text=text):
                self.assertEqual(scan_text(text + "\n"), [])

    def test_redacted_wording_and_out_of_scope_files_pass(self) -> None:
        few = "8"  # réglage d'exécution synthétique, sans contexte matériel
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme = f"ML350 Gen9 : CPU-only, bi-socket et NUMA.\n\nBenchmarks : {few} threads de calcul.\n"
            self.write(root, "README.md", readme)
            self.write(root, "docs/model/core-80m.md", "La cible est un ML350 bi-socket CPU-only.\n")
            self.write(root, "docs/notes.txt", SYNTHETIC_MODEL + "\n")
            self.write(root, "configs/runtime/host.md", SYNTHETIC_MODEL + "\n")
            self.assertEqual(scan_public_documents(root), [])

    def test_marker_split_by_a_line_break_or_unicode_hyphen_is_found(self) -> None:
        n = SYNTHETIC_CORES
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "docs/a.md", "ligne 1\n" + "E5\u2011" + "1234\n")
            self.write(root, "docs/b.md", "12" + "C/\n" + "24" + "T\n")
            self.write(root, "docs/c.md", f"Hôte synthétique.\nIl expose {n} threads.\n\nFin.\n")
            findings = scan_public_documents(root)
        self.assertEqual(
            findings,
            [
                ("docs/a.md", 2, "ml350-cpu-model"),
                ("docs/b.md", 1, "ml350-core-thread-count"),
                ("docs/c.md", 2, "ml350-core-thread-count"),
            ],
        )

    def test_an_empty_scan_set_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "configs/runtime/host.md", "bi-socket NUMA\n")
            with self.assertRaisesRegex(ValueError, "no public document found"):
                scan_public_documents(root)

    def test_oversized_or_non_utf8_documents_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "docs/large.md", "x" * 65)
            with self.assertRaisesRegex(ValueError, "exceeds 64 bytes"):
                scan_public_documents(root, max_bytes=64)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs" / "latin1.md").write_bytes(b"caract\xe8re\n")
            with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
                scan_public_documents(root)

    @unittest.skipIf(shutil.which("git") is None, "git indisponible")
    def test_only_tracked_documents_are_scanned_in_a_git_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "README.md", "Hôte bi-socket NUMA.\n")
            self.write(root, "docs/public.md", "CPU-only.\n")
            self.write(root, "docs/private-inventory.md", "64 Gio " + "visibles\n")
            self.git(root, "init", "-q")
            # Liste suivie vide : repli sur le parcours du système de fichiers.
            self.assertEqual(
                scan_public_documents(root), [("docs/private-inventory.md", 1, "ml350-visible-ram")]
            )
            self.git(root, "add", "--", "README.md", "docs/public.md")
            self.assertEqual(public_documents(root), sorted([root / "README.md", root / "docs" / "public.md"]))
            self.assertEqual(scan_public_documents(root), [])
            self.git(root, "add", "--", "docs/private-inventory.md")
            self.assertEqual(
                scan_public_documents(root), [("docs/private-inventory.md", 1, "ml350-visible-ram")]
            )

    def test_allowlist_entries_must_cite_an_active_exception_to_d025(self) -> None:
        decisions = {
            "D-003": " **SUPERSEDED par D-025.** | x |",
            "D-025": " Règle de rédaction synthétique. | x |",
            "D-900": " Dérogation synthétique à D-025 pour un inventaire. | x |",
            "D-901": " Licence synthétique acceptée pour le corpus. | x |",
            "D-902": " Calcul synthétique sur le ML350. | x |",
            "D-903": " Renvoi synthétique à D-0250. | x |",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "docs/inventory.md", SYNTHETIC_MODEL + "\n")
            entry = {"path": "docs/inventory.md", "marker": "ml350-cpu-model", "decision": "D-900"}
            self.assertEqual(
                validate_allowlist((entry,), root=root, decisions=decisions),
                {("docs/inventory.md", "ml350-cpu-model")},
            )
            refusals = {
                "D-xxx": dict(entry, decision="owner said so"),
                "absent from the register": dict(entry, decision="D-999"),
                "superseded": dict(entry, decision="D-003"),
                "itself": dict(entry, decision="D-025"),
                "unrelated licence decision": dict(entry, decision="D-901"),
                "unrelated ML350 decision": dict(entry, decision="D-902"),
                "look-alike identifier": dict(entry, decision="D-903"),
                "unknown marker": dict(entry, marker="ml350-anything"),
                "outside the public documents": dict(entry, path="configs/inventory.md"),
                "inside the repository": dict(entry, path="docs/../../inventory.md"),
                "does not exist": dict(entry, path="docs/missing.md"),
                "exactly the keys": {"path": "docs/inventory.md", "marker": "ml350-cpu-model"},
            }
            expected_messages = {
                "unrelated licence decision": "does not reference D-025",
                "unrelated ML350 decision": "does not reference D-025",
                "look-alike identifier": "does not reference D-025",
            }
            for case, bad in refusals.items():
                message = expected_messages.get(case, case)
                with self.subTest(case=case), self.assertRaisesRegex(ValueError, message):
                    validate_allowlist((bad,), root=root, decisions=decisions)
            self.write(root, "docs/inventory.md", "bi-socket NUMA\n")
            with self.assertRaisesRegex(ValueError, "stale"):
                validate_allowlist((entry,), root=root, decisions=decisions)

    def test_register_parsing_sees_d025_as_active(self) -> None:
        rows = register_rows(DECISIONS_PATH)
        self.assertIn("D-025", rows)
        self.assertNotIn("SUPERSEDED", rows["D-025"].upper())
        self.assertIn("SUPERSEDED", rows["D-003"].upper())

    def test_this_file_does_not_republish_the_markers_it_forbids(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertEqual(scan_text(source), [])
        # Ni empreinte hexadécimale, ni dictionnaire de valeurs à comparer.
        self.assertIsNone(re.search(r"(?<![0-9A-Fa-f])[0-9a-f]{32,}(?![0-9A-Fa-f])", source))


if __name__ == "__main__":
    unittest.main()
