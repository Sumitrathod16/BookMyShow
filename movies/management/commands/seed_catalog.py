"""
Seed genres, languages, and movies for filter/load testing.

Usage:
    python manage.py seed_catalog --count 5000
"""

import base64
import random
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from movies.models import Genre, Language, Movie

# 1x1 PNG
_PLACEHOLDER_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
)

GENRE_NAMES = [
    'Action', 'Comedy', 'Drama', 'Horror', 'Romance', 'Sci-Fi',
    'Thriller', 'Animation', 'Documentary', 'Fantasy',
]

LANGUAGE_NAMES = [
    'English', 'Hindi', 'Tamil', 'Telugu', 'Malayalam',
    'Kannada', 'Bengali', 'Marathi', 'Punjabi', 'Gujarati',
]


class Command(BaseCommand):
    help = 'Seed genres, languages, and movies for scalable filter testing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=5000,
            help='Number of movies to create (default: 5000)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all movies before seeding (keeps genres/languages)',
        )

    def handle(self, *args, **options):
        count = options['count']
        if count < 1:
            self.stderr.write(self.style.ERROR('--count must be at least 1'))
            return

        genres = self._ensure_genres()
        languages = self._ensure_languages()

        if options['clear']:
            deleted, _ = Movie.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'Deleted {deleted} movies.'))

        existing = Movie.objects.count()
        to_create = max(0, count - existing)
        if to_create == 0:
            self.stdout.write(
                self.style.SUCCESS(f'Already have {existing} movies (target {count}).')
            )
            return

        self.stdout.write(f'Creating {to_create} movies ({existing} already exist)...')
        placeholder = ContentFile(_PLACEHOLDER_PNG, name='placeholder.png')
        batch = []
        batch_size = 500

        with transaction.atomic():
            for i in range(to_create):
                n = existing + i + 1
                movie = Movie(
                    name=f'Seed Movie {n:05d}',
                    rating=round(random.uniform(1.0, 10.0), 1),
                    cast='Seed Cast',
                    description='Auto-generated for filter performance testing.',
                )
                movie.image.save(f'seed_{n:05d}.png', placeholder, save=False)
                batch.append(movie)

                if len(batch) >= batch_size:
                    self._flush_batch(batch, genres, languages)
                    batch = []

            if batch:
                self._flush_batch(batch, genres, languages)

        total = Movie.objects.count()
        self.stdout.write(self.style.SUCCESS(f'Done. {total} movies in catalog.'))

    def _ensure_genres(self):
        genres = []
        for name in GENRE_NAMES:
            genre, _ = Genre.objects.get_or_create(name=name)
            genres.append(genre)
        return genres

    def _ensure_languages(self):
        languages = []
        for name in LANGUAGE_NAMES:
            language, _ = Language.objects.get_or_create(name=name)
            languages.append(language)
        return languages

    def _flush_batch(self, movies, genres, languages):
        created = Movie.objects.bulk_create(movies)
        if created and created[0].pk is None:
            names = [m.name for m in movies]
            created = list(Movie.objects.filter(name__in=names).order_by('id'))

        genre_through = Movie.genres.through
        lang_through = Movie.languages.through
        genre_rows = []
        lang_rows = []
        for movie in created:
            for genre in random.sample(genres, k=random.randint(1, 3)):
                genre_rows.append(genre_through(movie_id=movie.pk, genre_id=genre.pk))
            for language in random.sample(languages, k=random.randint(1, 2)):
                lang_rows.append(lang_through(movie_id=movie.pk, language_id=language.pk))

        genre_through.objects.bulk_create(genre_rows, ignore_conflicts=True)
        lang_through.objects.bulk_create(lang_rows, ignore_conflicts=True)
        self.stdout.write(f'  … {Movie.objects.count()} movies')
