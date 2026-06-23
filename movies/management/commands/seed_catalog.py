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

SPECIFIC_MOVIES = [
    {
        'name': 'Avengers',
        'rating': 8.0,
        'cast': 'Robert Downey Jr., Chris Evans, Mark Ruffalo, Chris Hemsworth',
        'description': "Earth's mightiest heroes must come together and learn to fight as a team if they are to stop the mischievous Loki and his alien army from enslaving humanity.",
        'trailer_url': 'https://www.youtube.com/watch?v=eOrNdBpGMv8',
        'genres': ['Action', 'Sci-Fi'],
        'languages': ['English', 'Hindi', 'Tamil', 'Telugu'],
    },
    {
        'name': 'Interstellar',
        'rating': 8.7,
        'cast': 'Matthew McConaughey, Anne Hathaway, Jessica Chastain',
        'description': "When Earth becomes uninhabitable, a team of explorers travels through a wormhole in space in an attempt to ensure humanity's survival.",
        'trailer_url': 'https://www.youtube.com/watch?v=zSWdZAZE3nk',
        'genres': ['Sci-Fi', 'Drama'],
        'languages': ['English', 'Hindi'],
    },
    {
        'name': 'Inception',
        'rating': 8.8,
        'cast': 'Leonardo DiCaprio, Joseph Gordon-Levitt, Elliot Page',
        'description': "A thief who steals corporate secrets through the use of dream-sharing technology is given the inverse task of planting an idea into the mind of a C.E.O.",
        'trailer_url': 'https://www.youtube.com/watch?v=YoHD9XEInc0',
        'genres': ['Sci-Fi', 'Action', 'Thriller'],
        'languages': ['English', 'Hindi'],
    },
    {
        'name': 'Tenet',
        'rating': 7.3,
        'cast': 'John David Washington, Robert Pattinson, Elizabeth Debicki',
        'description': "Armed with only one word, Tenet, and fighting for the survival of the entire world, a Protagonist journeys through a twilight world of international espionage on a mission that will unfold in something beyond real time.",
        'trailer_url': 'https://www.youtube.com/watch?v=LdOM0x0XDwM',
        'genres': ['Sci-Fi', 'Action', 'Thriller'],
        'languages': ['English', 'Hindi'],
    },
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

        placeholder = ContentFile(_PLACEHOLDER_PNG, name='placeholder.png')

        # Ensure specific movies are seeded first
        with transaction.atomic():
            for spec in SPECIFIC_MOVIES:
                movie, created = Movie.objects.get_or_create(
                    name=spec['name'],
                    defaults={
                        'rating': spec['rating'],
                        'cast': spec['cast'],
                        'description': spec['description'],
                        'trailer_url': spec['trailer_url'],
                    }
                )
                if created:
                    movie.image.save(f"{spec['name'].lower()}_placeholder.png", placeholder, save=True)
                    # Add genres
                    for g_name in spec['genres']:
                        genre = next((g for g in genres if g.name == g_name), None)
                        if genre:
                            movie.genres.add(genre)
                    # Add languages
                    for l_name in spec['languages']:
                        lang = next((l for l in languages if l.name == l_name), None)
                        if lang:
                            movie.languages.add(lang)
                    self.stdout.write(f"Seeded specific movie: {spec['name']}")

        existing = Movie.objects.count()
        to_create = max(0, count - existing)
        if to_create == 0:
            self.stdout.write(
                self.style.SUCCESS(f'Already have {existing} movies (target {count}).')
            )
            return

        self.stdout.write(f'Creating {to_create} movies ({existing} already exist)...')
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
