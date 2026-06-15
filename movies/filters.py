"""
Scalable server-side movie filtering for large catalogs (5000+ rows).

Design choices:
- EXISTS subqueries on M2M through tables avoid JOIN + DISTINCT on the movie list.
- Facet counts use filtered Count(distinct=True) on small Genre/Language tables.
- Multi-select within one dimension = OR; genre AND language together = AND.
"""

from dataclasses import dataclass
from typing import Sequence

from django.db.models import Count, Exists, OuterRef, Q, QuerySet

from .models import Genre, Language, Movie


@dataclass(frozen=True)
class MovieFilterParams:
    search: str = ''
    genre_ids: tuple[int, ...] = ()
    language_ids: tuple[int, ...] = ()
    sort: str = 'name'

    @classmethod
    def from_request(cls, request) -> 'MovieFilterParams':
        return cls(
            search=request.GET.get('search', '').strip(),
            genre_ids=tuple(
                int(pk) for pk in request.GET.getlist('genre') if pk.isdigit()
            ),
            language_ids=tuple(
                int(pk) for pk in request.GET.getlist('language') if pk.isdigit()
            ),
            sort=request.GET.get('sort', 'name'),
        )

    @property
    def is_active(self) -> bool:
        return bool(self.search or self.genre_ids or self.language_ids)


_SORT_MAP = {
    'name': ('name',),
    'rating_asc': ('rating', 'name'),
    'rating_desc': ('-rating', 'name'),
}

_LIST_ONLY_FIELDS = ('id', 'name', 'rating', 'cast', 'image', 'description')


def _exists_for_genres(genre_ids: Sequence[int]) -> Exists:
    through = Movie.genres.through
    return Exists(
        through.objects.filter(
            movie_id=OuterRef('pk'),
            genre_id__in=genre_ids,
        )
    )


def _exists_for_languages(language_ids: Sequence[int]) -> Exists:
    through = Movie.languages.through
    return Exists(
        through.objects.filter(
            movie_id=OuterRef('pk'),
            language_id__in=language_ids,
        )
    )


def filter_movies(params: MovieFilterParams) -> QuerySet[Movie]:
    """
    Return movies matching filters, ordered for pagination.
    No .distinct() — each filter uses EXISTS so one row per movie.
    """
    qs = Movie.objects.all()

    if params.search:
        qs = qs.filter(name__icontains=params.search)

    if params.genre_ids:
        qs = qs.filter(_exists_for_genres(params.genre_ids))

    if params.language_ids:
        qs = qs.filter(_exists_for_languages(params.language_ids))

    order_by = _SORT_MAP.get(params.sort, ('name',))
    return (
        qs.only(*_LIST_ONLY_FIELDS)
        .order_by(*order_by)
        .prefetch_related('genres', 'languages')
    )


def _movies_matching_q(
    search: str,
    genre_ids: Sequence[int],
    language_ids: Sequence[int],
) -> Q:
    """Q object for reverse M2M facet counts (small genre/language tables)."""
    movie_filter = Q()
    if search:
        movie_filter &= Q(movies__name__icontains=search)
    if genre_ids:
        movie_filter &= Q(movies__genres__id__in=genre_ids)
    if language_ids:
        movie_filter &= Q(movies__languages__id__in=language_ids)
    return movie_filter


def get_genre_facets(
    search: str,
    selected_language_ids: Sequence[int],
) -> QuerySet[Genre]:
    """
    Count movies per genre given current search and language filters.
    Selected genres are excluded so counts reflect toggling other genres.
    """
    movie_filter = _movies_matching_q(search, (), selected_language_ids)
    return Genre.objects.annotate(
        movie_count=Count('movies', distinct=True, filter=movie_filter),
    ).order_by('name')


def get_language_facets(
    search: str,
    selected_genre_ids: Sequence[int],
) -> QuerySet[Language]:
    """Count movies per language given current search and genre filters."""
    movie_filter = _movies_matching_q(search, selected_genre_ids, ())
    return Language.objects.annotate(
        movie_count=Count('movies', distinct=True, filter=movie_filter),
    ).order_by('name')
