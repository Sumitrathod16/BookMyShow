# BookMySeat

A Django-based movie ticket booking web application.

## Features
- **Movie Catalog:** Browse and filter movies by genre and language.
- **Showtimes & Theaters:** View available showtimes for theaters.
- **Seat Map:** Interactive seat selection layout.
- **Email Confirmations:** An automated, durable email queue system that processes booking emails asynchronously.
- **Stripe Payments:** Integration for booking ticket checkouts.

## Local Setup

1. **Activate Virtual Environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Setup:**
   Copy the example environment file and fill in your credentials (database URL, Stripe keys, SMTP details):
   ```bash
   cp .env.example .env
   ```

4. **Run Migrations:**
   ```bash
   python manage.py migrate
   ```

5. **Seed Catalog Data (Optional):**
   ```bash
   python manage.py seed_catalog --count 15
   python manage.py seed_analytics_data
   ```

6. **Start Development Server:**
   ```bash
   python manage.py runserver
   ```

## Production Deployment

This project is configured to run on **Vercel** with a serverless setup:
- Pull configuration settings:
  ```bash
  npx vercel pull --yes --environment=production
  ```
- Deploy to production:
  ```bash
  npx vercel --prod --yes
  ```
