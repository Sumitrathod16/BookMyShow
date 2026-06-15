from django.test import TestCase, Client
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from movies.models import Movie, Theater, validate_youtube_url, extract_youtube_id


class TrailerValidatorTests(TestCase):
    def test_extract_youtube_id_valid(self):
        """Test extraction of YouTube video ID from various valid formats."""
        valid_urls = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?feature=shared&v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ]
        for url, expected in valid_urls:
            with self.subTest(url=url):
                self.assertEqual(extract_youtube_id(url), expected)

    def test_extract_youtube_id_invalid(self):
        """Test extraction fails for invalid or malicious URLs."""
        invalid_urls = [
            "",
            None,
            "https://www.google.com",
            "javascript:alert(1)",
            "https://youtube.com/watch?v=tooShort",
            "https://youtube.com/watch?v=tooLongVideoID123",
            "https://hacker.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/embed/dQw4w9WgXcQ/malicious",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertIsNone(extract_youtube_id(url))

    def test_validate_youtube_url_valid(self):
        """Test that validator permits valid URLs (no exception raised)."""
        validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        validate_youtube_url("https://youtu.be/dQw4w9WgXcQ")

    def test_validate_youtube_url_invalid(self):
        """Test that validator raises ValidationError on bad URLs."""
        with self.assertRaises(ValidationError):
            validate_youtube_url("https://malicious-domain.com/watch?v=dQw4w9WgXcQ")
        with self.assertRaises(ValidationError):
            validate_youtube_url("javascript:alert(1)")


class MovieTrailerModelTests(TestCase):
    def test_movie_properties(self):
        """Test model properties return correct video ID and embed URLs."""
        movie = Movie(
            name="Test Movie",
            rating=8.5,
            cast="Actor",
            image="movies/test.jpg",
            trailer_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        self.assertEqual(movie.youtube_video_id, "dQw4w9WgXcQ")
        self.assertEqual(movie.youtube_embed_url, "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_movie_properties_empty_trailer(self):
        """Test properties when trailer_url is empty."""
        movie = Movie(
            name="Test Movie No Trailer",
            rating=8.5,
            cast="Actor",
            image="movies/test.jpg"
        )
        self.assertIsNone(movie.youtube_video_id)
        self.assertIsNone(movie.youtube_embed_url)

    def test_movie_save_validation(self):
        """Test validation is run during full_clean of Movie model."""
        movie = Movie(
            name="Test Validation Movie",
            rating=8.5,
            cast="Actor",
            image="movies/test.jpg",
            trailer_url="https://google.com/hacked"
        )
        with self.assertRaises(ValidationError):
            movie.full_clean()


class MovieDetailsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.movie = Movie.objects.create(
            name="The Dark Knight",
            rating=9.0,
            cast="Christian Bale",
            description="Batman fight Joker.",
            image="movies/tdk.jpg",
            trailer_url="https://www.youtube.com/watch?v=EXeTwQWrcwY"
        )
        self.theater = Theater.objects.create(
            name="PVR Cinema",
            movie=self.movie,
            time=timezone.now() + timedelta(days=1),
            ticket_price=10.00
        )

    def test_theater_list_displays_trailer_details(self):
        """Test that the theater list view renders movie and trailer information."""
        url = reverse('theater_list', args=[self.movie.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Dark Knight")
        self.assertContains(response, "Christian Bale")
        self.assertContains(response, "Batman fight Joker.")
        # Check that the trailer play button with correct data-video-id is rendered
        self.assertContains(response, 'data-video-id="EXeTwQWrcwY"')
        # Ensure we didn't output raw youtube_url unsafely/directly
        self.assertNotContains(response, 'src="https://www.youtube.com/watch?v=')
