from datetime import date, time

from django.test import TestCase
from django.urls import reverse

from .models import Cours, Creneau, EmploiDuTemps, Option, Salle, Utilisateur


class ControleAccesRoleTests(TestCase):
    def setUp(self):
        self.option_info = Option.objects.create(nom="Informatique", niveau=1)
        self.option_math = Option.objects.create(nom="Mathématiques", niveau=1)
        self.cours_info = Cours.objects.create(
            codeCours="INFO101",
            intitule="Algorithmique",
            volumeHoraire="30h",
            option=self.option_info,
        )
        self.cours_math = Cours.objects.create(
            codeCours="MATH101",
            intitule="Analyse",
            volumeHoraire="30h",
            option=self.option_math,
        )
        self.salle = Salle.objects.create(nom="A101", capacite=40, site="Principal")
        self.cd = Utilisateur.objects.create_user(
            username="cd",
            email="cd@example.com",
            password="MotDePasseComplexe123",
            nom="Chef",
            prenom="Departement",
            role=Utilisateur.Role.CD,
        )
        self.enseignant = Utilisateur.objects.create_user(
            username="enseignant",
            email="enseignant@example.com",
            password="MotDePasseComplexe123",
            nom="Ens",
            prenom="Un",
            role=Utilisateur.Role.ENSEIGNANT,
        )
        self.autre_enseignant = Utilisateur.objects.create_user(
            username="autre-enseignant",
            email="autre@example.com",
            password="MotDePasseComplexe123",
            nom="Ens",
            prenom="Deux",
            role=Utilisateur.Role.ENSEIGNANT,
        )
        self.etudiant = Utilisateur.objects.create_user(
            username="etudiant",
            email="etudiant@example.com",
            password="MotDePasseComplexe123",
            nom="Etu",
            prenom="Info",
            role=Utilisateur.Role.ETUDIANT,
            option=self.option_info,
        )
        self.autre_etudiant = Utilisateur.objects.create_user(
            username="autre-etudiant",
            email="autre-etudiant@example.com",
            password="MotDePasseComplexe123",
            nom="Etu",
            prenom="Math",
            role=Utilisateur.Role.ETUDIANT,
            option=self.option_math,
        )
        self.emploi = EmploiDuTemps.objects.create(
            semaine=date(2026, 6, 1),
            statut=EmploiDuTemps.Statut.PUBLIE,
            creePar=self.cd,
        )
        Creneau.objects.create(
            emploiDuTemps=self.emploi,
            jour=Creneau.Jour.LUNDI,
            heureDebut=time(7, 30),
            heureFin=time(9, 30),
            cours=self.cours_info,
            enseignant=self.enseignant,
            salle=self.salle,
            option=self.option_info,
        )
        Creneau.objects.create(
            emploiDuTemps=self.emploi,
            jour=Creneau.Jour.MARDI,
            heureDebut=time(7, 30),
            heureFin=time(9, 30),
            cours=self.cours_math,
            enseignant=self.autre_enseignant,
            salle=self.salle,
            option=self.option_math,
        )

    def test_ressources_reservees_au_cd(self):
        routes = [
            reverse("enseignant_liste"),
            reverse("etudiant_liste"),
            reverse("cours_liste"),
            reverse("salle_liste"),
            reverse("option_liste"),
        ]
        self.client.force_login(self.enseignant)
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 403)

        self.client.force_login(self.cd)
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

    def test_enseignant_ne_consulte_que_son_emploi_du_temps(self):
        self.client.force_login(self.enseignant)
        response = self.client.get(reverse("detail_emploi_du_temps", args=[self.emploi.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Algorithmique")
        self.assertNotContains(response, "Analyse")

    def test_enseignant_non_affecte_est_refuse(self):
        enseignant_sans_creneau = Utilisateur.objects.create_user(
            username="enseignant-sans-creneau",
            email="enseignant-sans-creneau@example.com",
            password="MotDePasseComplexe123",
            nom="Sans",
            prenom="Cours",
            role=Utilisateur.Role.ENSEIGNANT,
        )
        self.client.force_login(enseignant_sans_creneau)
        response = self.client.get(reverse("detail_emploi_du_temps", args=[self.emploi.pk]))
        self.assertEqual(response.status_code, 403)

    def test_etudiant_ne_consulte_que_son_option(self):
        self.client.force_login(self.etudiant)
        response = self.client.get(reverse("detail_emploi_du_temps", args=[self.emploi.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Algorithmique")
        self.assertNotContains(response, "Analyse")

    def test_tableau_de_bord_etudiant_filtre_par_option(self):
        emploi_math = EmploiDuTemps.objects.create(
            semaine=date(2026, 6, 8),
            statut=EmploiDuTemps.Statut.PUBLIE,
            creePar=self.cd,
        )
        Creneau.objects.create(
            emploiDuTemps=emploi_math,
            jour=Creneau.Jour.LUNDI,
            heureDebut=time(7, 30),
            heureFin=time(9, 30),
            cours=self.cours_math,
            enseignant=self.autre_enseignant,
            salle=self.salle,
            option=self.option_math,
        )
        self.client.force_login(self.etudiant)
        response = self.client.get(reverse("tableau_de_bord"))
        self.assertEqual(list(response.context["emplois_du_temps"]), [self.emploi])
