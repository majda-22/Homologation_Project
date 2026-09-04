# R116 Platform

Plateforme desktop Flet pour piloter les workflows d'homologation R116 :
projets, maquettes, couverture, planning, CDC, notifications, reporting et
prediction DLL.

Stack principale : Flet, SQLAlchemy 2.0, SQLite, scikit-learn, ReportLab,
Argon2 et PyInstaller.

## Statut actuel

- Base de donnees SQLAlchemy : 16 tables metier.
- Authentification : login Flet, hash Argon2, utilisateur actif en session.
- Project : creation/liste/statut des projets, creation de maquettes.
- Homologation : creation, demarrage, dates jalons, statut, couverture.
- Couverture : suggestion par ArchitectureEE, decision couverte/non couverte,
  AuditLog, silhouettes couvertes ajoutees/retirees manuellement.
- EventBus : notifications automatiques sur changement de statut, demarrage
  homologation, decision couverture, retard detecte.
- Retards : detection automatique au chargement du Dashboard via
  Homologation.date_deadline, anti-doublon 24h.
- Planning : Kanban + vue Gantt detaillee par etapes, avec zoom semaine/mois/
  trimestre, scroll horizontal/vertical explicite, panneau de detail d'etape,
  priorite EDF calculee depuis la vraie date_deadline, reordonnancement
  automatique sur changement de deadline et retard detecte, generation
  theorique des 6 etapes par gabarit metier + residu ML, plus bouton manuel
  de recalcul.
- CDC : import des anciens fichiers Excel, suggestion automatique par
  similarite, edition des lignes, generation PDF dans le dossier Downloads
  de l'utilisateur.
- ML DLL : pipeline entrainable/testable avec garde-fous anti-fuite.
- ML Couverture : dataset supervise depuis DecisionCouverture, diagnostic de
  circularite, comparaison regle/logistic regression/arbre, affichage UI en
  parallele du moteur a regles.
- Reporting : dashboard de synthese et generation PDF de resume.
- Tests : workflows services/repositories principaux couverts.

## Etat ML

Le dataset actuel contient 20 lignes historiques dans
`data/raw/projects/Suivi_Homologation_R116.xlsx`.

Diagnostic actuel :

- Le gabarit fixe explique la majeure partie de la duree DLL.
- La cible ML actuelle est le residu `Dead Line avec BUFFER -> Dead Line`.
- Le residu vaut 0 jour sur 16/20 lignes ; les autres valeurs sont 4, 10,
  18 et 247 jours.
- Le meilleur modele honnete est la baseline du residu median historique.
- Les jalons bruts sont exclus des features pour eviter la fuite de donnees.
- La feature historique derivee reste documentee comme garde-fou EDA, mais
  elle n'est pas utilisee dans cette experience.

Derniers MAE LOOCV :

```text
baseline_residu_median  : 13.95 jours
ridge                   : 26.16 jours
kneighbors              : 21.33 jours
```

Artefact courant :

```text
ml_models/deadline_pipeline.joblib
model_name  = baseline_residu_median
target_mode = residu_buffer_deadline
prediction  = 231 jours + residu predit
```

## Gabarit Planning Theorique

Le generateur de planning construit les 6 etapes BF5.1 a partir d'une date
CMDE estimee et du residu DLL predit par le modele :

```text
Livraison CDC -> CMDE                 : 49 jours (20/20 lignes)
CMDE -> montage                       : 98 jours
montage -> validation fonctionnelle   : 35 jours
validation -> deadline avec buffer    : 56 jours
deadline avec buffer -> deadline      : residu ML
deadline -> retour estime             : 42 jours
```

Ces valeurs sont actuellement des regularites inferees des donnees. Elles
doivent etre confirmees par l'encadrant technique avant d'etre presentees
comme regles metier Capgemini documentees.

## Etat ML Couverture

La classification de couverture est branchee en phase de transition : l'ecran
"Verify Coverage" affiche le moteur a regles et le resultat ML cote a cote.

Dataset supervise :

```text
Source = DecisionCouverture join Homologation join Maquette
Features = silhouette_id, architecture_ee_id, fournisseur_id, type_homologation
Label = est_couverte
```

Dernier entrainement local :

```text
lignes_utilisables : 3
rule_baseline      : accuracy 0.67, precision 0.00, recall 0.00
logistic_regression: accuracy 0.67, precision 0.00, recall 0.00
decision_tree      : accuracy 0.67, precision 0.00, recall 0.00
modele retenu      : rule_baseline
```

Conclusion : aucun classifieur ne bat la regle pure avec les decisions
existantes. Dans l'etat actuel, aucun artefact `coverage_pipeline.joblib`
n'est distribue : la couverture reste donc portee par la regle metier
ArchitectureEE tant que le dataset supervise est trop petit.

## Demarrage rapide

```powershell
py -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
py -m app.infrastructure.database.init_db
py -m app.infrastructure.database.seed
py -m app.main
```

Compte administrateur :

```text
username: admin
password: genere au premier lancement
```

Au premier lancement sur une base vide, le mot de passe admin est ecrit dans :

```text
Downloads/R116_admin_password_PREMIERE_CONNEXION.txt
```

## Tests

```powershell
.\venv\Scripts\python.exe -m compileall app tests
.\venv\Scripts\python.exe -m pytest -v
```

Etat verifie :

```text
48 passed
```

## Donnees et artefacts

```text
data/raw/cdc/                         anciens CDC Excel
data/raw/projects/Suivi_Homologation_R116.xlsx
ml_models/deadline_pipeline.joblib
Downloads utilisateur                 PDFs generes
```

## Packaging PyInstaller

Le packaging valide en premier est le mode `onedir`, plus fiable avec Flet,
pandas et scikit-learn :

```powershell
.\venv\Scripts\pyinstaller.exe R116Platform.spec
```

Le spec est configure en mode windowed (`console=False`) et n'embarque pas
`data/` ni `ml_models/`. Ces dossiers restent externes et mutables, au meme
niveau que l'executable :

```text
dist/R116Platform/
  R116Platform.exe
  data/
    r116.db
  ml_models/
    deadline_pipeline.joblib
  _internal/
```

Sur base vide, l'application cree le compte `admin` et ecrit le mot de passe
dans le dossier Downloads de l'utilisateur. Les PDF CDC et resumes projet
sortent aussi dans Downloads, jamais dans un dossier interne a l'application.

Sans certificat de signature de code, Windows SmartScreen peut afficher un
avertissement "editeur inconnu" au premier lancement. C'est attendu pour une
distribution interne non signee.

## Structure

```text
app/
  main.py
  config/
  shared/
  domain/
    project/
    homologation/
    planning/
    notification/
    reporting/
  application/
    auth/
    project/
    homologation/
    planning/
    notification/
    reporting/
  infrastructure/
    database/
    ml/
    reporting/
  presentation/
tests/
data/
ml_models/
```

## Reste a faire

- Verifier avec la source metier le doublon suspect X2/M1/Y8 et X3/M2/Y10 a
  597 jours.
- Mettre a jour le rapport Chapitre 8 avec les MAE et le diagnostic gabarit.
- Ajouter des variables explicatives de retard reel : cause retard, fournisseur
  responsable, non-conformite, blocage validation, etc.
- Ajouter des tests UI/end-to-end Flet si necessaire.
- Durcir les permissions par role dans l'interface.
- Valider le build PyInstaller sur une machine Windows propre sans Python.
