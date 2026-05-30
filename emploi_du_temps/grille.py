from datetime import time

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
    {"id": "0730-0930", "debut": time(7, 30), "fin": time(9, 30), "label": "7H30 - 9H30"},
    {"id": "0930-1130", "debut": time(9, 30), "fin": time(11, 30), "label": "9H30 - 11H30"},
    {"id": "1130-1330", "debut": time(11, 30), "fin": time(13, 30), "label": "11H30 - 13H30"},
    {"id": "1330-1400", "debut": time(13, 30), "fin": time(14, 0), "label": "13H30 - 14H00", "pause": True},
    {"id": "1400-1600", "debut": time(14, 0), "fin": time(16, 0), "label": "14H00 - 16H00"},
]


def trouver_plage(plage_id: str) -> dict | None:
    """Retrouver une plage horaire officielle à partir de son identifiant."""
    for plage in PLAGES_HORAIRES:
        if plage["id"] == plage_id:
            return plage
    return None


def construire_grille(emploi_du_temps: EmploiDuTemps) -> list[dict]:
    """Construire les lignes du tableau officiel avec les créneaux existants."""
    creneaux = Creneau.objects.filter(emploiDuTemps=emploi_du_temps).select_related(
        "cours", "enseignant", "salle"
    )
    creneaux_par_cellule = {
        (creneau.jour, creneau.heureDebut, creneau.heureFin): creneau
        for creneau in creneaux
    }

    lignes = []
    for plage in PLAGES_HORAIRES:
        if plage.get("pause"):
            lignes.append({"plage": plage, "pause": True, "cellules": []})
            continue

        cellules = []
        for code_jour, libelle_jour in JOURS_EDT:
            creneau = creneaux_par_cellule.get((code_jour, plage["debut"], plage["fin"]))
            cellules.append(
                {
                    "jour": code_jour,
                    "jour_label": libelle_jour,
                    "plage": plage,
                    "creneau": creneau,
                }
            )
        lignes.append({"plage": plage, "pause": False, "cellules": cellules})

    return lignes