# TIME_TABLE — Gestion Emploi du Temps

Application Django simple de gestion d'emploi du temps académique.

## Règles métier conservées

- Le Chef de département gère les ressources, crée, modifie, supprime et publie les emplois du temps.
- Les enseignants et étudiants consultent uniquement les emplois du temps publiés.

## Structure simplifiée

- `config/settings.py` : configuration Django unique et simple avec SQLite.
- `emploi_du_temps/` : application métier avec les modèles en français : `Utilisateur`, `CD`, `Enseignant`, `Etudiant`, `Option`, `Cours`, `Salle`, `EmploiDuTemps`, `Creneau`, `Conflit`.
- `requirements.txt` : dépendance minimale du projet.

## Clonage du projet

```bash
git clone https://github.com/obouny/TIME_TABLE.git
cd TIME_TABLE
```

## Commandes à lancer

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Commandes de vérification

```bash
python manage.py check
python -m compileall config emploi_du_temps
```
