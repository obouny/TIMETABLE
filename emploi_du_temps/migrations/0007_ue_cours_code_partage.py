# Generated manually to introduce UE and allow several courses to share the UE code.

import django.db.models.deletion
from django.db import migrations, models


def creer_ues_depuis_cours(apps, schema_editor):
    UE = apps.get_model("emploi_du_temps", "UE")
    Cours = apps.get_model("emploi_du_temps", "Cours")
    for cours in Cours.objects.all():
        ue, _ = UE.objects.get_or_create(
            codeUE=cours.codeCours,
            defaults={"intituleUE": cours.intitule},
        )
        cours.ue = ue
        cours.save(update_fields=["ue"])


class Migration(migrations.Migration):

    dependencies = [
        ("emploi_du_temps", "0006_utilisateur_option"),
    ]

    operations = [
        migrations.CreateModel(
            name="UE",
            fields=[
                (
                    "codeUE",
                    models.CharField(
                        max_length=30,
                        primary_key=True,
                        serialize=False,
                        verbose_name="code UE",
                    ),
                ),
                ("intituleUE", models.CharField(max_length=200, verbose_name="intitulé UE")),
            ],
            options={
                "verbose_name": "UE",
                "verbose_name_plural": "UE",
                "ordering": ["codeUE"],
            },
        ),
        migrations.AddField(
            model_name="cours",
            name="ue",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cours",
                to="emploi_du_temps.ue",
                verbose_name="UE",
            ),
        ),
        migrations.RunPython(creer_ues_depuis_cours, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="creneau",
            name="cours",
        ),
        migrations.AlterField(
            model_name="cours",
            name="codeCours",
            field=models.CharField(editable=False, max_length=30, verbose_name="code du cours"),
        ),
        migrations.AddField(
            model_name="cours",
            name="id",
            field=models.BigAutoField(
                auto_created=True,
                primary_key=True,
                serialize=False,
                verbose_name="ID",
            ),
        ),
        migrations.AlterField(
            model_name="cours",
            name="intitule",
            field=models.CharField(max_length=200, verbose_name="intitulé du cours"),
        ),
        migrations.AlterField(
            model_name="cours",
            name="ue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cours",
                to="emploi_du_temps.ue",
                verbose_name="UE",
            ),
        ),
        migrations.AlterModelOptions(
            name="cours",
            options={
                "ordering": ["codeCours", "intitule"],
                "verbose_name": "cours",
                "verbose_name_plural": "cours",
            },
        ),
        migrations.AddField(
            model_name="creneau",
            name="cours",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="creneaux",
                to="emploi_du_temps.cours",
                verbose_name="cours",
            ),
        ),
    ]
