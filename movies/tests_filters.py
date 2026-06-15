import base64

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory

from movies.filters import MovieFilterParams, filter_movies, get_genre_facets, get_language_facets
from movies.models import Genre, Language, Movie

_PLACEHOLDER = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=='
)


class MovieFilterTests(TestCase):
    def setUp(self):
        self.placeholder = SimpleUploadedFile('t.png', _PLACEHOLDER, content_type='image/png')
        self.action = Genre.objects.create(name='Action')
        self.comedy = Genre.objects.create(name='Comedy')
        self.hindi = Language.objects.create(name='Hindi')
        self.english = Language.objects.create(name='English')

        self.m1 = Movie.objects.create(
            name='Alpha Action', rating=8.0, cast='A', description='',
            image=self.placeholder,
        )
        self.m1.genres.add(self.action)
        self.m1.languages.add(self.hindi)

        self.m2 = Movie.objects.create(
            name='Beta Comedy', rating=7.0, cast='B', description='',
            image=self.placeholder,
        )
        self.m2.genres.add(self.comedy)
        self.m2.languages.add(self.english)

        self.m3 = Movie.objects.create(
            name='Gamma Mix', rating=9.0, cast='C', description='',
            image=self.placeholder,
        )
        self.m3.genres.add(self.action, self.comedy)
        self.m3.languages.add(self.hindi, self.english)

    def test_filter_by_single_genre(self):
        params = MovieFilterParams(genre_ids=(self.action.pk,))
        ids = set(filter_movies(params).values_list('pk', flat=True))
        self.assertEqual(ids, {self.m1.pk, self.m3.pk})

    def test_filter_genre_and_language_and(self):
        params = MovieFilterParams(
            genre_ids=(self.action.pk,),
            language_ids=(self.english.pk,),
        )
        ids = set(filter_movies(params).values_list('pk', flat=True))
        self.assertEqual(ids, {self.m3.pk})

    def test_search_and_sort(self):
        params = MovieFilterParams(search='Alpha', sort='rating_desc')
        results = list(filter_movies(params))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, 'Alpha Action')

    def test_facet_counts_respect_other_filters(self):
        genres = {g.pk: g.movie_count for g in get_genre_facets('', (self.hindi.pk,))}
        self.assertEqual(genres[self.action.pk], 2)
        self.assertEqual(genres[self.comedy.pk], 1)

    def test_from_request_parses_multi_select(self):
        factory = RequestFactory()
        url = (
            f'/movies/?genre={self.action.pk}&genre={self.comedy.pk}'
            f'&language={self.hindi.pk}&search=foo&sort=rating_desc'
        )
        request = factory.get(url)
        params = MovieFilterParams.from_request(request)
        self.assertEqual(len(params.genre_ids), 2)
        self.assertEqual(len(params.language_ids), 1)
        self.assertEqual(params.search, 'foo')
        self.assertEqual(params.sort, 'rating_desc')
