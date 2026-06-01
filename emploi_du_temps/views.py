from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from emploi_du_temps.forms import CreneauDirectForm, EmploiDuTempsForm
from emploi_du_temps.grille import JOURS_EDT, PLAGES_HORAIRES, construire_grille_semaine, trouver_plage
from emploi_du_temps.permissions import cd_requis
from .models import Cours, Creneau, EmploiDuTemps, Option, Salle, Utilisateur


class ConnexionView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        return reverse_lazy("tableau_de_bord")


def accueil(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("tableau_de_bord")
    return render(request, "emploi_du_temps/accueil.html")


@login_required
def tableau_de_bord(request: HttpRequest) -> HttpResponse:
    utilisateur = request.user
    context = {"utilisateur": utilisateur}

    if utilisateur.role == Utilisateur.Role.CD:
        template = "emploi_du_temps/tableaux_de_bord/cd.html"
        context.update({
            "nb_enseignants": Utilisateur.objects.filter(role=Utilisateur.Role.ENSEIGNANT).count(),
            "nb_cours": Cours.objects.count(),
            "nb_salles": Salle.objects.count(),
            "nb_options": Option.objects.count(),
            "nb_emplois": EmploiDuTemps.objects.count(),
            "nb_brouillons": EmploiDuTemps.objects.filter(statut=EmploiDuTemps.Statut.BROUILLON).count(),
            "nb_publies": EmploiDuTemps.objects.filter(statut=EmploiDuTemps.Statut.PUBLIE).count(),
            "emplois_recents": EmploiDuTemps.objects.select_related("creePar")[:5],
        })
    elif utilisateur.role == Utilisateur.Role.ENSEIGNANT:
        template = "emploi_du_temps/tableaux_de_bord/enseignant.html"
        context["emplois_du_temps"] = EmploiDuTemps.objects.filter(
            statut=EmploiDuTemps.Statut.PUBLIE,
            creneaux__enseignant=utilisateur,
        ).distinct()
    elif utilisateur.role == Utilisateur.Role.ETUDIANT:
        template = "emploi_du_temps/tableaux_de_bord/etudiant.html"
        context["emplois_du_temps"] = EmploiDuTemps.objects.filter(
            statut=EmploiDuTemps.Statut.PUBLIE
        )
    else:
        return HttpResponseForbidden("Rôle utilisateur non autorisé.")

    return render(request, template, context)


def deconnexion(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.success(request, "Vous êtes déconnecté.")
    return redirect("login")


# ─────────────────────────────────────────────
#  GRILLE EDT PAR SEMAINE (style PHP)
# ─────────────────────────────────────────────

def _get_lundi(semaine_str: str | None) -> date:
    """Retourne le lundi de la semaine donnée ou de la semaine courante."""
    if semaine_str:
        try:
            d = date.fromisoformat(semaine_str)
            return d - timedelta(days=d.weekday())
        except ValueError:
            pass
    today = date.today()
    return today - timedelta(days=today.weekday())


@login_required
def grille_edt(request: HttpRequest, semaine: str | None = None) -> HttpResponse:
    """Grille EDT par semaine — vue principale (équivalent PHP /edt)."""
    semaine_date = _get_lundi(semaine or request.GET.get("semaine"))
    salles = Salle.objects.all()
    salle_id_param = request.GET.get("salle_id", "")
    try:
        salle_id = int(salle_id_param) if salle_id_param else None
    except (TypeError, ValueError):
        salle_id = None
    if salle_id and not salles.filter(pk=salle_id).exists():
        salle_id = None
    if not salle_id:
        premiere_salle = salles.first()
        salle_id = premiere_salle.pk if premiere_salle else None
    est_cd = request.user.role == Utilisateur.Role.CD

    lignes = construire_grille_semaine(
        semaine_date,
        salle_id=salle_id,
    )

    # Semaines déjà planifiées
    semaines_dispo = (
        EmploiDuTemps.objects.values_list("semaine", flat=True)
        .distinct()
        .order_by("semaine")
    )

    # Emplois de cette semaine (pour publication / export)
    emplois_semaine = EmploiDuTemps.objects.filter(semaine=semaine_date).prefetch_related("creneaux")

    return render(request, "emploi_du_temps/grille/index.html", {
        "semaine": semaine_date,
        "semaine_prev": semaine_date - timedelta(weeks=1),
        "semaine_next": semaine_date + timedelta(weeks=1),
        "jours": JOURS_EDT,
        "lignes": lignes,
        "plages": PLAGES_HORAIRES,
        "salles": salles,
        "salle_id_actif": salle_id,
        "semaines_dispo": semaines_dispo,
        "est_cd": est_cd,
        "emplois_semaine": emplois_semaine,
    })


@cd_requis
def ajouter_creneau_grille(request: HttpRequest) -> HttpResponse:
    """Formulaire d'ajout d'un créneau depuis la grille (équivalent PHP /edt/create)."""
    semaine_str = request.GET.get("semaine") or request.POST.get("semaine") or str(date.today())
    semaine_date = _get_lundi(semaine_str)

    # Préremplissage si clic sur une cellule
    salle_initiale = request.GET.get("salle") or request.GET.get("salle_id") or ""
    if salle_initiale:
        try:
            salle_initiale = str(Salle.objects.get(pk=int(salle_initiale)).pk)
        except (Salle.DoesNotExist, TypeError, ValueError):
            salle_initiale = ""

    initial = {
        "semaine": semaine_date,
        "salle": salle_initiale,
        "jour": request.GET.get("jour", ""),
        "plage": request.GET.get("plage", ""),
    }

    if request.method == "POST":
        form = CreneauDirectForm(request.POST)
        if form.is_valid():
            # On récupère ou crée l'EmploiDuTemps brouillon global pour cette semaine.
            # Toujours utiliser LE LUNDI de la semaine comme clé
            semaine_lundi = _get_lundi(str(form.cleaned_data["semaine"]))
            emploi, _ = EmploiDuTemps.objects.get_or_create(
                semaine=semaine_lundi,
                defaults={"creePar": request.user, "statut": EmploiDuTemps.Statut.BROUILLON},
            )
            try:
                plage = trouver_plage(form.cleaned_data["plage"])
                creneau = Creneau(
                    emploiDuTemps=emploi,
                    option=form.cleaned_data["cours"].option,
                    jour=form.cleaned_data["jour"],
                    heureDebut=plage["debut"],
                    heureFin=plage["fin"],
                    cours=form.cleaned_data["cours"],
                    enseignant=form.cleaned_data["enseignant"],
                    salle=form.cleaned_data["salle"],
                )
                creneau.full_clean()
                creneau.save()
                messages.success(request, "Créneau ajouté avec succès.")
            except ValidationError as e:
                for msg in e.messages:
                    messages.error(request, msg)
                return render(request, "emploi_du_temps/grille/formulaire.html", {
                    "form": form,
                    "semaine": semaine_date,
                    "titre": "Ajouter un créneau",
                    "plages": PLAGES_HORAIRES,
                    "jours": JOURS_EDT,
                })
            return redirect(f"/emplois-du-temps/grille/{semaine_lundi.isoformat()}/?salle_id={form.cleaned_data['salle'].pk}")

        return render(request, "emploi_du_temps/grille/formulaire.html", {
            "form": form,
            "semaine": semaine_date,
            "titre": "Ajouter un créneau",
            "plages": PLAGES_HORAIRES,
            "jours": JOURS_EDT,
        })

    form = CreneauDirectForm(initial=initial)
    return render(request, "emploi_du_temps/grille/formulaire.html", {
        "form": form,
        "semaine": semaine_date,
        "titre": "Ajouter un créneau",
        "plages": PLAGES_HORAIRES,
        "jours": JOURS_EDT,
    })


@cd_requis
def modifier_creneau_grille(request: HttpRequest, pk: int) -> HttpResponse:
    """Modifier un créneau depuis la grille."""
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps", "cours", "enseignant", "salle", "option"), pk=pk)
    semaine = creneau.emploiDuTemps.semaine

    if request.method == "POST":
        form = CreneauDirectForm(request.POST, instance=creneau)
        if form.is_valid():
            try:
                plage = trouver_plage(form.cleaned_data["plage"])
                creneau.jour = form.cleaned_data["jour"]
                creneau.heureDebut = plage["debut"]
                creneau.heureFin = plage["fin"]
                creneau.cours = form.cleaned_data["cours"]
                creneau.option = form.cleaned_data["cours"].option
                creneau.enseignant = form.cleaned_data["enseignant"]
                creneau.salle = form.cleaned_data["salle"]
                creneau.full_clean()
                creneau.save()
                messages.success(request, "Créneau modifié avec succès.")
            except ValidationError as e:
                for msg in e.messages:
                    messages.error(request, msg)
                return render(request, "emploi_du_temps/grille/formulaire.html", {
                    "form": form, "semaine": semaine, "titre": "Modifier un créneau",
                    "creneau": creneau, "plages": PLAGES_HORAIRES, "jours": JOURS_EDT,
                })
            return redirect(f"/emplois-du-temps/grille/{semaine.isoformat()}/?salle_id={creneau.salle_id}")
    else:
        # Préremplir le formulaire avec les valeurs existantes
        # Trouver la plage correspondante
        plage_id = ""
        for p in PLAGES_HORAIRES:
            if p["debut"] == creneau.heureDebut and p["fin"] == creneau.heureFin:
                plage_id = p["id"]
                break
        form = CreneauDirectForm(initial={
            "semaine": semaine.isoformat(),
            "jour": creneau.jour,
            "plage": plage_id,
            "cours": creneau.cours,
            "enseignant": creneau.enseignant,
            "salle": creneau.salle,
        }, instance=creneau)

    return render(request, "emploi_du_temps/grille/formulaire.html", {
        "form": form, "semaine": semaine, "titre": "Modifier un créneau",
        "creneau": creneau, "plages": PLAGES_HORAIRES, "jours": JOURS_EDT,
    })


@cd_requis
def supprimer_creneau_grille(request: HttpRequest, pk: int) -> HttpResponse:
    """Supprimer un créneau depuis la grille."""
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    semaine = creneau.emploiDuTemps.semaine
    if request.method == "POST":
        creneau.delete()
        messages.success(request, "Créneau supprimé.")
        return redirect(f"/emplois-du-temps/grille/{semaine.isoformat()}/?salle_id={creneau.salle_id}")
    return render(request, "emploi_du_temps/grille/confirmer_suppression.html", {
        "creneau": creneau, "semaine": semaine,
    })


@cd_requis
def publier_semaine(request: HttpRequest) -> HttpResponse:
    """Publie tous les emplois du temps brouillons de la semaine donnée."""
    if request.method != "POST":
        return redirect("grille_edt")
    semaine_str = request.POST.get("semaine", "")
    semaine_lundi = _get_lundi(semaine_str)
    emplois = EmploiDuTemps.objects.filter(semaine=semaine_lundi, statut=EmploiDuTemps.Statut.BROUILLON)
    count = emplois.update(statut=EmploiDuTemps.Statut.PUBLIE, datePublication=timezone.now())
    if count:
        messages.success(request, f"{count} emploi(s) du temps publié(s) pour la semaine du {semaine_lundi.strftime('%d/%m/%Y')}.")
    else:
        messages.info(request, "Aucun brouillon à publier pour cette semaine.")
    return redirect(f"/emplois-du-temps/grille/{semaine_lundi.isoformat()}/")


@cd_requis
def depublier_semaine(request: HttpRequest) -> HttpResponse:
    """Repasse les emplois du temps de la semaine en brouillon."""
    if request.method != "POST":
        return redirect("grille_edt")
    semaine_str = request.POST.get("semaine", "")
    semaine_lundi = _get_lundi(semaine_str)
    count = EmploiDuTemps.objects.filter(semaine=semaine_lundi, statut=EmploiDuTemps.Statut.PUBLIE).update(statut=EmploiDuTemps.Statut.BROUILLON)
    messages.success(request, f"{count} emploi(s) repassé(s) en brouillon.")
    return redirect(f"/emplois-du-temps/grille/{semaine_lundi.isoformat()}/")


@cd_requis
def ajax_conflits(request: HttpRequest) -> JsonResponse:
    """Vérification AJAX des conflits (équivalent PHP /edt/check-conflicts)."""
    if request.method != "POST":
        return JsonResponse({"conflits": [], "count": 0})

    semaine_str = request.POST.get("semaine", "")
    cours_id = request.POST.get("cours_id")
    enseignant_id = request.POST.get("enseignant_id")
    salle_id = request.POST.get("salle_id")
    plage_id = request.POST.get("plage", "")
    jour = request.POST.get("jour", "")
    exclude_id = request.POST.get("exclude_id")

    plage = trouver_plage(plage_id)
    if not plage or not semaine_str or not jour:
        return JsonResponse({"conflits": [], "count": 0})

    try:
        semaine_date = _get_lundi(semaine_str)
    except Exception:
        return JsonResponse({"conflits": [], "count": 0})

    qs = Creneau.objects.filter(
        emploiDuTemps__semaine=semaine_date,
        jour=jour,
        heureDebut__lt=plage["fin"],
        heureFin__gt=plage["debut"],
    ).select_related("cours", "enseignant", "salle", "option")

    if exclude_id:
        try:
            qs = qs.exclude(pk=int(exclude_id))
        except (TypeError, ValueError):
            pass

    conflits = []
    if salle_id:
        try:
            qs_salle = qs.filter(salle_id=int(salle_id))
        except (TypeError, ValueError):
            qs_salle = Creneau.objects.none()
        for c in qs_salle:
            conflits.append({
                "type": "salle",
                "message": f"Conflit de SALLE : « {c.salle.nom} » est déjà occupée le {c.get_jour_display()} de {c.heureDebut.strftime('%H:%M')} à {c.heureFin.strftime('%H:%M')} par le cours {c.cours.intitule} ({c.enseignant.prenom} {c.enseignant.nom}).",
            })
    if enseignant_id:
        try:
            qs_enseignant = qs.filter(enseignant_id=int(enseignant_id))
        except (TypeError, ValueError):
            qs_enseignant = Creneau.objects.none()
        for c in qs_enseignant:
            conflits.append({
                "type": "enseignant",
                "message": f"Conflit d'ENSEIGNANT : {c.enseignant.nom} {c.enseignant.prenom} est déjà programmé(e) le {c.get_jour_display()} de {c.heureDebut.strftime('%H:%M')} à {c.heureFin.strftime('%H:%M')} en salle {c.salle.nom} pour le cours {c.cours.intitule}.",
            })
    option_id = None
    if cours_id:
        option_id = Cours.objects.filter(pk=cours_id).values_list("option_id", flat=True).first()
    if option_id:
        for c in qs.filter(option_id=option_id):
            conflits.append({
                "type": "option",
                "message": f"Conflit OPTION : l'option « {c.option.nom} » a déjà un cours le {c.get_jour_display()} de {c.heureDebut.strftime('%H:%M')} à {c.heureFin.strftime('%H:%M')} ({c.cours.intitule} — salle {c.salle.nom}).",
            })

    # Dédupliquer
    seen = set()
    unique = []
    for conf in conflits:
        if conf["message"] not in seen:
            seen.add(conf["message"])
            unique.append(conf)

    return JsonResponse({"conflits": unique, "count": len(unique)})


@login_required
def ajax_cours_par_option(request: HttpRequest, option_id: int) -> JsonResponse:
    """Retourne les cours d'une option (équivalent PHP /edt/cours-par-filiere)."""
    cours = list(Cours.objects.filter(option_id=option_id).values("codeCours", "intitule"))
    return JsonResponse(cours, safe=False)


# ─────────────────────────────────────────────
#  EMPLOIS DU TEMPS (liste + gestion statut)
# ─────────────────────────────────────────────

@login_required
@cd_requis
def liste_emplois_du_temps(request: HttpRequest) -> HttpResponse:
    emplois_du_temps = EmploiDuTemps.objects.select_related("creePar")
    return render(request, "emploi_du_temps/emplois_du_temps/liste.html", {
        "emplois_du_temps": emplois_du_temps,
    })


@cd_requis
def creer_emploi_du_temps(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EmploiDuTempsForm(request.POST)
        if form.is_valid():
            emploi = form.save(commit=False)
            emploi.creePar = request.user
            emploi.statut = EmploiDuTemps.Statut.BROUILLON
            emploi.save()
            messages.success(request, "Emploi du temps brouillon créé.")
            return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    else:
        form = EmploiDuTempsForm()
    return render(request, "emploi_du_temps/emplois_du_temps/formulaire.html", {
        "form": form, "titre": "Créer un emploi du temps",
    })


@login_required
def detail_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(
        EmploiDuTemps.objects.select_related("creePar")
        .prefetch_related("creneaux__cours", "creneaux__enseignant", "creneaux__salle"),
        pk=pk,
    )
    est_cd = request.user.role == Utilisateur.Role.CD
    if not est_cd and emploi.statut != EmploiDuTemps.Statut.PUBLIE:
        return HttpResponseForbidden("Cet emploi du temps n'est pas encore publié.")
    return render(request, "emploi_du_temps/emplois_du_temps/detail.html", {
        "emploi_du_temps": emploi, "est_cd": est_cd,
    })


@cd_requis
def modifier_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        form = EmploiDuTempsForm(request.POST, instance=emploi)
        if form.is_valid():
            form.save()
            messages.success(request, "Emploi du temps modifié.")
            return redirect("detail_emploi_du_temps", pk=emploi.pk)
    else:
        form = EmploiDuTempsForm(instance=emploi)
    return render(request, "emploi_du_temps/emplois_du_temps/formulaire.html", {
        "form": form, "titre": "Modifier un emploi du temps",
    })


@cd_requis
def supprimer_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        emploi.delete()
        messages.success(request, "Emploi du temps supprimé.")
        return redirect("liste_emplois_du_temps")
    return render(request, "emploi_du_temps/emplois_du_temps/confirmer_suppression.html", {
        "emploi_du_temps": emploi,
    })


@cd_requis
def publier_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(EmploiDuTemps, pk=pk)
    if request.method == "POST":
        emploi.statut = EmploiDuTemps.Statut.PUBLIE
        emploi.datePublication = timezone.now()
        emploi.save(update_fields=["statut", "datePublication"])
        messages.success(request, "Emploi du temps publié.")
    return redirect("detail_emploi_du_temps", pk=emploi.pk)


@cd_requis
def editeur_emploi_du_temps(request: HttpRequest, pk: int) -> HttpResponse:
    emploi = get_object_or_404(
        EmploiDuTemps.objects.select_related("creePar"), pk=pk
    )
    from emploi_du_temps.grille import construire_grille
    creneaux = list(emploi.creneaux.select_related("salle"))
    sites = sorted({c.salle.site for c in creneaux if c.salle.site})
    salles = sorted({c.salle.nom for c in creneaux if c.salle.nom})
    return render(request, "emploi_du_temps/emplois_du_temps/editeur.html", {
        "emploi_du_temps": emploi,
        "jours": JOURS_EDT,
        "lignes": construire_grille(emploi),
        "plages": PLAGES_HORAIRES,
        "date_fin_semaine": emploi.semaine + timedelta(days=5),
        "site_officiel": sites[0] if len(sites) == 1 else "à préciser",
        "salle_officielle": salles[0] if len(salles) == 1 else "selon créneau",
    })


@cd_requis
def ajouter_creneau(request: HttpRequest, emploi_pk: int) -> HttpResponse:
    from emploi_du_temps.forms import CreneauForm
    emploi = get_object_or_404(EmploiDuTemps, pk=emploi_pk)
    if request.method == "POST":
        form = CreneauForm(request.POST, emploi_du_temps=emploi)
        if form.is_valid():
            form.save()
            messages.success(request, "Créneau ajouté.")
            return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    else:
        plage = trouver_plage(request.GET.get("plage", ""))
        jour = request.GET.get("jour")
        initial = {}
        if plage and not plage.get("pause") and jour:
            initial = {"jour": jour, "heureDebut": plage["debut"], "heureFin": plage["fin"]}
        form = CreneauForm(emploi_du_temps=emploi, initial=initial)
    return render(request, "emploi_du_temps/creneaux/formulaire.html", {
        "form": form, "emploi_du_temps": emploi, "titre": "Ajouter un créneau",
    })


@cd_requis
def modifier_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    from emploi_du_temps.forms import CreneauForm
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = creneau.emploiDuTemps
    if request.method == "POST":
        form = CreneauForm(request.POST, instance=creneau, emploi_du_temps=emploi)
        if form.is_valid():
            form.save()
            messages.success(request, "Créneau modifié.")
            return redirect("detail_emploi_du_temps", pk=emploi.pk)
    else:
        form = CreneauForm(instance=creneau, emploi_du_temps=emploi)
    return render(request, "emploi_du_temps/creneaux/formulaire.html", {
        "form": form, "emploi_du_temps": emploi, "titre": "Modifier un créneau",
    })


@cd_requis
def supprimer_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = creneau.emploiDuTemps
    if request.method == "POST":
        creneau.delete()
        messages.success(request, "Créneau supprimé.")
        return redirect("detail_emploi_du_temps", pk=emploi.pk)
    return render(request, "emploi_du_temps/creneaux/confirmer_suppression.html", {
        "creneau": creneau, "emploi_du_temps": emploi,
    })


def _reponse_edition_cellule(request, emploi, message, statut=200):
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"message": message}, status=statut)
    if statut >= 400:
        messages.error(request, message)
    else:
        messages.success(request, message)
    return redirect("editeur_emploi_du_temps", pk=emploi.pk)


@cd_requis
def deplacer_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    creneau = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = creneau.emploiDuTemps
    if request.method != "POST":
        return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    plage = trouver_plage(request.POST.get("plage", ""))
    jour = request.POST.get("jour", "")
    if not plage or plage.get("pause") or jour not in dict(JOURS_EDT):
        return _reponse_edition_cellule(request, emploi, "Plage ou jour invalide.", 400)
    creneau.jour = jour
    creneau.heureDebut = plage["debut"]
    creneau.heureFin = plage["fin"]
    try:
        creneau.full_clean()
    except ValidationError as e:
        return _reponse_edition_cellule(request, emploi, " ".join(e.messages), 400)
    creneau.save()
    return _reponse_edition_cellule(request, emploi, "Créneau déplacé.")


@cd_requis
def copier_creneau(request: HttpRequest, pk: int) -> HttpResponse:
    source = get_object_or_404(Creneau.objects.select_related("emploiDuTemps"), pk=pk)
    emploi = source.emploiDuTemps
    if request.method != "POST":
        return redirect("editeur_emploi_du_temps", pk=emploi.pk)
    plage = trouver_plage(request.POST.get("plage", ""))
    jour = request.POST.get("jour", "")
    if not plage or plage.get("pause") or jour not in dict(JOURS_EDT):
        return _reponse_edition_cellule(request, emploi, "Plage ou jour invalide.", 400)
    copie = Creneau(
        emploiDuTemps=emploi, cours=source.cours,
        enseignant=source.enseignant, salle=source.salle, option=source.option,
        jour=jour, heureDebut=plage["debut"], heureFin=plage["fin"],
    )
    try:
        copie.full_clean()
    except ValidationError as e:
        return _reponse_edition_cellule(request, emploi, " ".join(e.messages), 400)
    copie.save()
    return _reponse_edition_cellule(request, emploi, "Créneau copié.")


# ─────────────────────────────────────────────
#  RESSOURCES
# ─────────────────────────────────────────────

@login_required
def enseignant_liste(request):
    enseignants = Utilisateur.objects.filter(role=Utilisateur.Role.ENSEIGNANT)
    return render(request, "emploi_du_temps/ressources/enseignants/liste.html", {"enseignants": enseignants})

@login_required
def enseignant_creer(request):
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        prenom = request.POST.get("prenom", "").strip()
        email = request.POST.get("email", "").strip()
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        if not all([nom, email, username, password]):
            messages.error(request, "Tous les champs marqués * sont obligatoires.")
        elif Utilisateur.objects.filter(email=email).exists():
            messages.error(request, "Cet email est déjà utilisé.")
        elif Utilisateur.objects.filter(username=username).exists():
            messages.error(request, "Ce nom d'utilisateur est déjà pris.")
        else:
            Utilisateur.objects.create_user(username=username, email=email, password=password,
                nom=nom, prenom=prenom, role=Utilisateur.Role.ENSEIGNANT)
            messages.success(request, f"Enseignant {nom} {prenom} créé avec succès.")
            return redirect("enseignant_liste")
    return render(request, "emploi_du_temps/ressources/enseignants/form.html", {"action": "Créer", "enseignant": None})

@login_required
def enseignant_modifier(request, pk):
    enseignant = get_object_or_404(Utilisateur, pk=pk, role=Utilisateur.Role.ENSEIGNANT)
    if request.method == "POST":
        enseignant.nom = request.POST.get("nom", enseignant.nom).strip()
        enseignant.prenom = request.POST.get("prenom", enseignant.prenom).strip()
        enseignant.email = request.POST.get("email", enseignant.email).strip()
        enseignant.save()
        messages.success(request, "Enseignant modifié avec succès.")
        return redirect("enseignant_liste")
    return render(request, "emploi_du_temps/ressources/enseignants/form.html", {"action": "Modifier", "enseignant": enseignant})

@login_required
def enseignant_supprimer(request, pk):
    enseignant = get_object_or_404(Utilisateur, pk=pk, role=Utilisateur.Role.ENSEIGNANT)
    if request.method == "POST":
        enseignant.delete()
        messages.success(request, "Enseignant supprimé.")
        return redirect("enseignant_liste")
    return render(request, "emploi_du_temps/ressources/enseignants/confirmer_suppression.html", {"enseignant": enseignant})

@login_required
def cours_liste(request):
    cours = Cours.objects.select_related("option").all()
    return render(request, "emploi_du_temps/ressources/cours/liste.html", {"cours": cours})

@login_required
def cours_creer(request):
    options = Option.objects.all()
    if request.method == "POST":
        code = request.POST.get("codeCours", "").strip()
        intitule = request.POST.get("intitule", "").strip()
        volume = request.POST.get("volumeHoraire", "").strip()
        option_id = request.POST.get("option")
        if not all([code, intitule, option_id]):
            messages.error(request, "Tous les champs marqués * sont obligatoires.")
        elif Cours.objects.filter(codeCours=code).exists():
            messages.error(request, "Ce code cours existe déjà.")
        else:
            Cours.objects.create(codeCours=code, intitule=intitule, volumeHoraire=volume, option_id=option_id)
            messages.success(request, f"Cours {intitule} créé avec succès.")
            return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/form.html", {"action": "Créer", "cours": None, "options": options})

@login_required
def cours_modifier(request, pk):
    cours = get_object_or_404(Cours, codeCours=pk)
    options = Option.objects.all()
    if request.method == "POST":
        cours.intitule = request.POST.get("intitule", cours.intitule).strip()
        cours.volumeHoraire = request.POST.get("volumeHoraire", cours.volumeHoraire).strip()
        cours.option_id = request.POST.get("option", cours.option_id)
        cours.save()
        messages.success(request, "Cours modifié avec succès.")
        return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/form.html", {"action": "Modifier", "cours": cours, "options": options})

@login_required
def cours_supprimer(request, pk):
    cours = get_object_or_404(Cours, codeCours=pk)
    if request.method == "POST":
        cours.delete()
        messages.success(request, "Cours supprimé.")
        return redirect("cours_liste")
    return render(request, "emploi_du_temps/ressources/cours/confirmer_suppression.html", {"cours": cours})

@login_required
def salle_liste(request):
    salles = Salle.objects.all()
    return render(request, "emploi_du_temps/ressources/salles/liste.html", {"salles": salles})

@login_required
def salle_creer(request):
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        capacite = request.POST.get("capacite", "").strip()
        site = request.POST.get("site", "").strip()
        if not all([nom, capacite, site]):
            messages.error(request, "Tous les champs sont obligatoires.")
        else:
            Salle.objects.create(nom=nom, capacite=int(capacite), site=site)
            messages.success(request, f"Salle {nom} créée avec succès.")
            return redirect("salle_liste")
    return render(request, "emploi_du_temps/ressources/salles/form.html", {"action": "Créer", "salle": None})

@login_required
def salle_modifier(request, pk):
    salle = get_object_or_404(Salle, pk=pk)
    if request.method == "POST":
        salle.nom = request.POST.get("nom", salle.nom).strip()
        salle.capacite = int(request.POST.get("capacite", salle.capacite))
        salle.site = request.POST.get("site", salle.site).strip()
        salle.save()
        messages.success(request, "Salle modifiée avec succès.")
        return redirect("salle_liste")
    return render(request, "emploi_du_temps/ressources/salles/form.html", {"action": "Modifier", "salle": salle})

@login_required
def salle_supprimer(request, pk):
    salle = get_object_or_404(Salle, pk=pk)
    if request.method == "POST":
        salle.delete()
        messages.success(request, "Salle supprimée.")
        return redirect("salle_liste")
    return render(request, "emploi_du_temps/ressources/salles/confirmer_suppression.html", {"salle": salle})

@login_required
def option_liste(request):
    options = Option.objects.all()
    return render(request, "emploi_du_temps/ressources/options/liste.html", {"options": options})

@login_required
def option_creer(request):
    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        niveau = request.POST.get("niveau", "").strip()
        if not all([nom, niveau]):
            messages.error(request, "Tous les champs sont obligatoires.")
        else:
            Option.objects.create(nom=nom, niveau=int(niveau))
            messages.success(request, f"Option {nom} créée avec succès.")
            return redirect("option_liste")
    return render(request, "emploi_du_temps/ressources/options/form.html", {"action": "Créer", "option": None})

@login_required
def option_modifier(request, pk):
    option = get_object_or_404(Option, pk=pk)
    if request.method == "POST":
        option.nom = request.POST.get("nom", option.nom).strip()
        option.niveau = int(request.POST.get("niveau", option.niveau))
        option.save()
        messages.success(request, "Option modifiée avec succès.")
        return redirect("option_liste")
    return render(request, "emploi_du_temps/ressources/options/form.html", {"action": "Modifier", "option": option})

@login_required
def option_supprimer(request, pk):
    option = get_object_or_404(Option, pk=pk)
    if request.method == "POST":
        option.delete()
        messages.success(request, "Option supprimée.")
        return redirect("option_liste")
    return render(request, "emploi_du_temps/ressources/options/confirmer_suppression.html", {"option": option})
