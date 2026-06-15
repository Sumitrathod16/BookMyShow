# Movie filtering — performance design (5000+ catalog)

## Requirements covered

- Multi-select **genre** and **language** filters (server-side, GET params).
- **Pagination** (`page`) and **sorting** (`sort`) preserved across filter combinations.
- **Dynamic facet counts** on the sidebar (counts update when other filters change).
- **Indexed** M2M through tables and sort columns to avoid full-table scans where possible.

## Query strategy (`movies/filters.py`)

### Movie list — `EXISTS` instead of `JOIN` + `DISTINCT`

Previously, filtering used:

```python
Movie.objects.filter(genres__id__in=...).filter(languages__id__in=...).distinct()
```

With several M2M joins, the database returns **multiple rows per movie**, then deduplicates. At 5000+ movies this is expensive.

**Current approach:** one `EXISTS` subquery per dimension, indexed on `movies_movie_genres` / `movies_movie_languages`:

- No duplicate movie rows → **no `.distinct()`** on the list query.
- SQLite/PostgreSQL can use `(genre_id, movie_id)` indexes for the subquery.

### Filter semantics

| Dimension | Multi-select behavior |
|-----------|------------------------|
| Genres | **OR** — movie has any selected genre |
| Languages | **OR** — movie has any selected language |
| Genre + language together | **AND** — must match both dimensions |

### Facet counts (sidebar badges)

Genre counts use: current **search** + selected **languages** (not selected genres).

Language counts use: current **search** + selected **genres** (not selected languages).

This is standard **faceted search**: each option shows how many results you get if you add/toggle that facet.

Implementation: `Count('movies', distinct=True, filter=Q(...))` on small `Genre` / `Language` tables (~10–50 rows). Cost is acceptable; genre table scans are not 5000-wide.

### Search (`name__icontains`)

Substring search **does not use** the B-tree index on `name` efficiently (leading wildcard).

| Trade-off | Choice |
|-----------|--------|
| Flexibility | `icontains` — users search any part of title |
| Scale | PostgreSQL `SearchVector` + GIN index for production |
| Dev | SQLite is fine for demos; use PostgreSQL for load tests |

### Pagination

`Paginator` runs `COUNT(*)` on the filtered queryset once per request. With `EXISTS` filters, count stays cheaper than join+distinct.

**Trade-off:** offset pagination (`page=500`) slows on very deep pages; **cursor pagination** is a future improvement.

### List queryset slimming

`.only('id', 'name', 'rating', 'cast', 'image', 'description')` avoids loading unused columns on list pages.

`.prefetch_related('genres', 'languages')` avoids N+1 on the card template (2 extra queries per page, not per movie).

## Indexes (`0003_filter_performance_indexes`)

| Index | Purpose |
|-------|---------|
| `movies_movie_rating_name_idx` | Sort by rating then name |
| `movies_movie_genres (genre_id, movie_id)` | Genre `EXISTS` / facet joins |
| `movies_movie_genres (movie_id, genre_id)` | Reverse lookups |
| `movies_movie_languages (language_id, movie_id)` | Language `EXISTS` |
| `movies_movie_languages (movie_id, language_id)` | Reverse lookups |

## Load testing

```bash
python manage.py migrate
python manage.py seed_catalog --count 5000
python manage.py runserver
```

Open `/movies/`, apply filters, and inspect queries (Django Debug Toolbar or `django.db.connection.queries` in shell).

## Files

| File | Role |
|------|------|
| `movies/filters.py` | Filter params, list queryset, facet queries |
| `movies/views.py` | `movie_list` view wires filters + pagination |
| `movies/migrations/0003_*.py` | Performance indexes |
| `movies/management/commands/seed_catalog.py` | Test data generator |
