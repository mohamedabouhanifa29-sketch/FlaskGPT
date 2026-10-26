# FlaskGPT — Conversations et analyse de données

Application web Flask utilisant Groq pour discuter, consulter des documents et analyser des données avec des sources vérifiables. Projet Python géré par Poetry ; interface Tailwind et JavaScript.

## Fonctionnalités

- Conversations persistantes dans SQLite, nouvelle conversation et effacement de la conversation active.
- Domaines général, informatique, finance, analyse de données et autre.
- Réponses en streaming et messages explicites pour clés invalides, quotas, connexion, délais et modèle indisponible.
- Import PDF/TXT/CSV/XLSX ; sources cochables et nombre de lignes, paragraphes ou extraits réglable.
- Citations cliquables vers les passages utilisés, avec contrôle de l'existence des références.
- Résumé PDF extractif de la conversation et export complet TXT, Markdown, PDF ou JSON.
- Import d'une copie SQLite/CSV/XLSX et requêtes SQL en lecture seule.
- Indicateurs de complétude, doublons, homogénéité des types, anomalies numériques possibles et règles métier.
- Durée, premier token et tokens par réponse et conversation, avec couverture des mesures.
- Notes utilisateur : satisfaisante (vert), moyenne (ambre), insuffisante (rouge).

## Installation

Prérequis : Python 3.11+, Poetry 2+ et une clé Groq. Le CSS compilé est inclus ; Node.js 20+ n'est nécessaire que pour reconstruire les styles.

```powershell
git clone https://github.com/mohamedabouhanifa29-sketch/FlaskGPT.git
cd FlaskGPT
poetry install
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Dans `.env`, renseigner `SECRET_KEY` avec le résultat généré et `GROQ_API_KEY` avec votre propre clé. `GROQ_MODEL` doit désigner un modèle accessible dans votre compte ; le défaut est `openai/gpt-oss-20b`.

```powershell
poetry run python app.py
```

Ouvrir **http://127.0.0.1:5000**. Dans PyCharm, utiliser l'interpréteur `.venv` et lancer `app.py` ou `main.py`. La configuration `[tool.uv] package = false` permet aussi le lancement par uv sans construire un paquet.

Alternative :

```powershell
uv run python app.py
```

Le professeur ou toute personne qui clone le dépôt doit configurer sa propre clé. Le code public ne contient pas la clé, les conversations ou les bases de données de l'auteur.

## Documents et sources

Importer un document dans **Sources à consulter**, puis poser une question. Les sources sélectionnées peuvent être envoyées à Groq avec la question. Décocher une source l'exclut des prochaines demandes ; les passages associés aux anciennes réponses restent consultables. Les anciens messages ne sont réutilisés que si leur domaine et leurs réglages de sources correspondent à la demande actuelle.

Limites : 8 Mio par fichier, 12 sources par conversation, 120 000 caractères extraits ; PDF texte non chiffré de 100 pages maximum, sans OCR. TXT UTF-8 ; CSV documentaire séparé par virgules ; XLSX sans exécution des formules. Les valeurs des formules proviennent des caches du classeur.

De 1 à 10 éléments par source peuvent être demandés, avec un maximum global de 24 passages et 24 000 caractères ; chaque extrait est borné à 1600 caractères. La recherche est lexicale, pas exhaustive. Les références [S1], [S2], etc. sont propres à chaque réponse.

**Une citation existante ne garantit pas la vérité ni que chaque affirmation est étayée.** Sans référence reconnue, l'application indique une absence de preuve documentaire vérifiable. Les couleurs correspondent à la note humaine, pas à un score de confiance du modèle.

## Analyse et gouvernance des données

Dans **Données & gouvernance**, importer SQLite (.db/.sqlite/.sqlite3), CSV ou XLSX. Les rapports sont calculés localement. Les sources des bases importées et des résultats SQL sont décochées par défaut ; les cocher autorise l'utilisation de leurs extraits par le chat.

Les CSV/XLSX sont convertis en copies SQLite avec des tables `table_1`, `table_2`, etc. Les séparateurs virgule, point-virgule ou tabulation sont détectés pour les CSV de données. Les en-têtes vides/répétés et les lignes de longueur incohérente sont signalés.

Le rapport indique :

- Part des cellules non manquantes (nulles, vides ou composées d'espaces).
- Doublons exacts de lignes et part de lignes uniques.
- Types inférés et types minoritaires dans chaque colonne.
- Valeurs numériques atypiques selon les bornes Q1−1,5×IQR / Q3+1,5×IQR, à vérifier.
- Échecs de structure et respect des règles définies par l'utilisateur.

Exemple de règles métier :

```json
{
  "required": ["email"],
  "types": {"age": "number"},
  "ranges": {"age": {"min": 0, "max": 120}}
}
```

Les types acceptés sont number, date ISO et text. Les valeurs manquantes sont contrôlées par required. Une colonne attendue absente est signalée. Les règles sont appliquées à chaque table de la base sélectionnée ; sans règle applicable, le respect des règles est non évalué.

Pour essayer : importer `tests/fixtures/qualite.csv` (données fictives). Il contient 7 lignes, 2 cellules manquantes, 1 doublon, 1 type minoritaire et 1 anomalie numérique possible. Les règles ci-dessus donnent 4 échecs sur 19 contrôles.

Les profils portent sur au plus 20 tables ordinaires, 100 colonnes et 2000 lignes par table ; l'échantillonnage est indiqué. CSV/XLSX : 2000 lignes de données et 120 000 caractères au total. SQLite : 120 000 caractères de valeurs échantillonnées et délai de calcul de 3 secondes. Vues, tables virtuelles et BLOB non pris en charge. XLSX : au plus 24 Mio décompressés et 1000 entrées d'archive.

Les indicateurs sont techniques : ils ne certifient pas une conformité réglementaire, une exactitude métier ou des relations intertables.

## Requêtes SQL

Sélectionner une base importée, puis saisir par exemple :

```sql
SELECT name FROM sqlite_master WHERE type='table';
SELECT COUNT(*) FROM table_1;
```

Une seule instruction SELECT/WITH, connexion en lecture seule, authorizer SQLite avec liste de fonctions autorisées ; écritures, ATTACH, PRAGMA et extensions refusés. Délai de 2 secondes, 200 lignes et 120 000 caractères maximum. Aucun SQL du modèle n'est exécuté automatiquement.

Une base serveur SQLite peut être autorisée avec `ANALYSIS_SQLITE_PATH`. Le navigateur ne peut pas fournir un chemin arbitraire. PostgreSQL/MySQL/SQL Server nécessitent un connecteur supplémentaire, un compte SELECT seulement, TLS, un périmètre de vues autorisées et des limites côté serveur.

## Performances, export et résumé

Les compteurs de tokens proviennent des événements Groq (usage/x_groq.usage). Ils restent inconnus si le fournisseur ne les communique pas ; les totaux connus sont partiels et leur couverture est affichée. La durée et le premier token sont mesurés côté serveur. Aucun coût monétaire ou pourcentage de confiance n'est inventé.

Le résumé PDF copie une introduction bornée à 600 caractères des 20 derniers messages, avec état et références citées : c'est un résumé extractif non exhaustif. Les exports complets conservent messages, sources, erreurs, mesures et notes. Le JSON ajoute les réglages et les rapports de données.

Arrêter interrompt la lecture du navigateur ; le serveur peut terminer avant de détecter la déconnexion. L'historique conserve les réponses partielles.

## Tests

```powershell
poetry run pytest -q
poetry run python -m compileall -q app.py main.py governance.py tests
node --check static/script.js
poetry check
```

**34 tests automatisés réussis** lors de la validation locale. Ils utilisent des données temporaires, des fournisseurs simulés et le vrai SDK Groq avec un transport HTTP simulé. Ils ne nécessitent pas de clé et n'appellent pas le réseau. Une réponse réelle a également été vérifiée séparément avec un simple message de test. Détails dans [TESTS.md](TESTS.md).

## Styles

```powershell
npm ci
npm run build:css
```

## Organisation

```text
app.py                  Routes, stockage, chat, migrations et PDF
main.py                 Lanceur alternatif pour PyCharm
governance.py           Imports, profilage et règles métier
templates/index.html    Interface
static/script.js        Streaming, citations, notes et indicateurs
static/input.css        Entrée Tailwind
static/tailwind.css      Styles compilés
tests/                  Tests et CSV d'exemple
```

## Sécurité et exploitation

Les secrets `.env`, les données `instance/`, les environnements et la configuration IDE sont exclus de Git. Le cookie signé identifie un navigateur ; ce n'est pas un compte utilisateur. Garder SECRET_KEY stable. Les données sont conservées localement sans chiffrement au repos : protéger le dossier et les sauvegardes. Effacer une conversation ne supprime pas les copies déjà exportées ou sauvegardées.

L'application vise un usage personnel local. Avant exposition sur Internet : ajouter une authentification, des quotas, HTTPS, COOKIE_SECURE=true et une isolation mémoire/CPU des parseurs. Les uploads et les consignes du modèle ne garantissent pas à eux seuls l'absence de fichiers hostiles ou d'injections de prompt.
