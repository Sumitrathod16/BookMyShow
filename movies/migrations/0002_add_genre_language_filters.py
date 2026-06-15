from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Genre',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, db_index=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Language',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, db_index=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='movie',
            name='genres',
            field=models.ManyToManyField(blank=True, related_name='movies', to='movies.Genre'),
        ),
        migrations.AddField(
            model_name='movie',
            name='languages',
            field=models.ManyToManyField(blank=True, related_name='movies', to='movies.Language'),
        ),
        migrations.AlterField(
            model_name='movie',
            name='name',
            field=models.CharField(db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='movie',
            name='rating',
            field=models.DecimalField(db_index=True, decimal_places=1, max_digits=3),
        ),
    ]
