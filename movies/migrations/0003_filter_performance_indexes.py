from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0002_add_genre_language_filters'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='movie',
            index=models.Index(fields=['rating', 'name'], name='movies_movie_rating_name_idx'),
        ),
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS movies_movie_genres_genre_movie_idx ON movies_movie_genres (genre_id, movie_id);',
            reverse_sql='DROP INDEX IF EXISTS movies_movie_genres_genre_movie_idx;',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS movies_movie_genres_movie_genre_idx ON movies_movie_genres (movie_id, genre_id);',
            reverse_sql='DROP INDEX IF EXISTS movies_movie_genres_movie_genre_idx;',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS movies_movie_languages_lang_movie_idx ON movies_movie_languages (language_id, movie_id);',
            reverse_sql='DROP INDEX IF EXISTS movies_movie_languages_lang_movie_idx;',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX IF NOT EXISTS movies_movie_languages_movie_lang_idx ON movies_movie_languages (movie_id, language_id);',
            reverse_sql='DROP INDEX IF EXISTS movies_movie_languages_movie_lang_idx;',
        ),
    ]
