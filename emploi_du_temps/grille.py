from datetime import date, time

from .models import Creneau, EmploiDuTemps

JOURS_EDT = [
    ("LUNDI", "Lundi"),
    ("MARDI", "Mardi"),
    ("MERCREDI", "Mercredi"),
    ("JEUDI", "Jeudi"),
    ("VENDREDI", "Vendredi"),
    ("SAMEDI", "Samedi"),
]

PLAGES_HORAIRES = [
    {"id": "0730-0930", "debut": time(7, 30), "fin": time(9, 30),  "label": "7H30 - 9H30"},
    {"id": "0930-1130", "debut": time(9, 30), "fin": time(11, 30), "label": "9H30 - 11H30"},
    {"id": "1130-1330", "debut": time(11, 30),"fin": time(13, 30), "label": "11H30 - 13H30"},
    {"id": "1330-1400", "debut": time(13, 30),"fin": time(14, 0),  "label": "13H30 - 14H00", "pause": True},
    {"id": "1400-1600", "debut": time(14, 0), "fin": time(16, 0),  "label": "14H00 - 16H00"},
]


def trouver_plage(plage_id: str) -> dict | None:
    for plage in PLAGES_HORAIRES:
        if plage["id"] == plage_id:
            return plage
    return None


def construire_grille(emploi_du_temps: EmploiDuTemps) -> list[dict]:
    """Grille pour l'éditeur d'un EmploiDuTemps spécifique."""
    creneaux = Creneau.objects.filter(emploiDuTemps=emploi_du_temps).select_related(
        "cours__ue", "cours", "enseignant", "salle"
    )
    creneaux_par_cellule = {
        (c.jour, c.heureDebut, c.heureFin): c for c in creneaux
    }
    lignes = []
    for plage in PLAGES_HORAIRES:
        if plage.get("pause"):
            lignes.append({"plage": plage, "pause": True, "cellules": []})
            continue
        cellules = []
        for code_jour, libelle_jour in JOURS_EDT:
            creneau = creneaux_par_cellule.get((code_jour, plage["debut"], plage["fin"]))
            cellules.append({
                "jour": code_jour,
                "jour_label": libelle_jour,
                "plage": plage,
                "creneau": creneau,
            })
        lignes.append({"plage": plage, "pause": False, "cellules": cellules})
    return lignes


def construire_grille_semaine(
    semaine: date,
    salle_id: int | None = None,
    utilisateur=None,
) -> list[dict]:
    """Grille hebdomadaire d'une salle donnée, filtrée selon le rôle utilisateur."""
    qs = Creneau.objects.filter(
        emploiDuTemps__semaine=semaine,
    ).select_related("cours__ue", "cours", "enseignant", "salle", "option", "emploiDuTemps")

    if utilisateur and utilisateur.is_authenticated:
        if utilisateur.role == utilisateur.Role.ENSEIGNANT:
            qs = qs.filter(emploiDuTemps__statut=EmploiDuTemps.Statut.PUBLIE, enseignant=utilisateur)
        elif utilisateur.role == utilisateur.Role.ETUDIANT:
            qs = qs.filter(emploiDuTemps__statut=EmploiDuTemps.Statut.PUBLIE)
            if utilisateur.option_id:
                qs = qs.filter(option=utilisateur.option)
            else:
                qs = qs.none()
        elif utilisateur.role != utilisateur.Role.CD:
            qs = qs.none()

    if salle_id:
        qs = qs.filter(salle_id=salle_id)

    creneaux_par_cellule: dict[tuple, list] = {}
    for c in qs:
        key = (c.jour, c.heureDebut, c.heureFin)
        creneaux_par_cellule.setdefault(key, []).append(c)

    lignes = []
    for plage in PLAGES_HORAIRES:
        if plage.get("pause"):
            lignes.append({"plage": plage, "pause": True, "cellules": []})
            continue
        cellules = []
        for code_jour, libelle_jour in JOURS_EDT:
            key = (code_jour, plage["debut"], plage["fin"])
            cellules.append({
                "jour": code_jour,
                "jour_label": libelle_jour,
                "plage": plage,
                "creneaux": creneaux_par_cellule.get(key, []),
            })
        lignes.append({"plage": plage, "pause": False, "cellules": cellules})
    return lignes
