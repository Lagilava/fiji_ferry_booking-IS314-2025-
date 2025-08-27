# Fiji Ferry Booking System - IS314 Project

**Team**: Group 10  
**Supervisor**: Mr. Ravneil Nand  
**Semester**: 2, 2025

## Project Overview

The Fiji Ferry Booking System is a web platform to streamline ferry travel in Fiji. It enables users to book tickets, make payments, view real-time schedules, and manage bookings, reducing reliance on physical ticket counters. The system improves accessibility for residents in suburbs, interiors, and outer islands.

## Key Features

- **Online Ticket Booking**: Choose routes, dates, and passenger numbers.
- **Secure Payments**: Integrated with Stripe for safe transactions.
- **Real-Time Schedules**: Live updates on ferry availability and seats.
- **QR Code Ticketing**: Scannable QR codes for tickets and cargo.
- **Booking Management**: View history and cancel bookings online.
- **Weather Updates**: Real-time route weather (e.g., "Patchy rain nearby, 25°C, Wind 29.5kph").

## Technology Stack

- **Backend**: Python, Django
- **Database**: MySQL (SQLite for development)
- **Frontend**: HTML, CSS, JavaScript
- **APIs**: WeatherAPI, Stripe
- **Methodology**: Agile

## Setup Instructions

Follow these beginner-friendly steps to set up the project locally with MySQL Workbench. Each step includes verification and troubleshooting tips.

### Step 1: Install Prerequisites

Install and verify the following tools:

1. **Python 3.8+**:
   - Download: [python.org](https://www.python.org/downloads/)
   - Verify: `python --version` (Windows) or `python3 --version` (Mac/Linux)
   - **Troubleshooting**: Ensure Python is added to PATH during installation.

2. **Git**:
   - Download: [git-scm.com](https://git-scm.com/downloads)
   - Verify: `git --version`
   - **Troubleshooting**: Install Git if not found and add to PATH.

3. **MySQL and MySQL Workbench**:
   - Download: [mysql.com](https://www.mysql.com/products/community/)
   - Start MySQL Server:
     - **Windows**: Use MySQL Installer
     - **Mac**: `brew install mysql; brew services start mysql`
     - **Linux**: `sudo apt-get install mysql-server; sudo service mysql start`
   - Verify: Connect in Workbench to `localhost:3306` with username `root` and password
   - **Troubleshooting**:
     - Connection error: Check server status (`mysqladmin -u root -p status`)
     - Password reset: `ALTER USER 'root'@'localhost' IDENTIFIED BY 'new_password';`

4. **MySQL Client Library**:
   - Install: `pip install mysqlclient`
   - **Troubleshooting**:
     - `mysql_config not found`:
       - **Windows**: Install MySQL Connector/C
       - **Mac**: `brew install mysql-connector-c`
       - **Linux**: `sudo apt-get install libmysqlclient-dev`

### Step 2: Clone Repository

Clone and navigate to the project directory:

```bash
git clone <repository-url>
cd fiji_ferry_booking
```

- Replace `<repository-url>` with the actual URL.
- Verify: Ensure `manage.py` and `requirements.txt` are in the directory.
- **Troubleshooting**: Confirm Git is installed and repository access is granted.

### Step 3: Set Up Virtual Environment

Isolate dependencies with a virtual environment:

- **Windows**:
  ```bash
  python -m venv venv
  venv\Scripts\activate
  ```
- **Mac/Linux**:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

- Verify: Prompt shows `(venv)`; `pip --version` confirms virtual environment `pip`.
- **Troubleshooting**: Ensure Python version matches (`python3` for Mac/Linux).

### Step 4: Install Dependencies

Install required packages:

```bash
pip install -r requirements.txt
```

- Includes Django, `mysqlclient`, `stripe`, `requests`, `celery`, etc.
- Verify: `pip list` shows all packages.
- **Troubleshooting**:
  - Fix `mysqlclient` errors (see Step 1).
  - Reinstall: `pip install --force-reinstall -r requirements.txt`.

### Step 5: Configure MySQL Database

Set up the database using MySQL Workbench:

1. **Connect to MySQL**:
   - Open Workbench, connect to `localhost:3306` (username: `root`, your password).
   - Verify: “Test Connection” succeeds.

2. **Create Database**:
   - Run in a new query tab:
     ```sql
     CREATE DATABASE fiji_ferry_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
     ```
   - Verify: `SHOW DATABASES;` lists `fiji_ferry_db`.

3. **Set Environment Variables**:
   - Copy `.env`:
     ```bash
     cp .env.example .env
     ```
   - Edit `.env`:
     ```
     SECRET_KEY=your-secret-key
     DEBUG=True
     ALLOWED_HOSTS=localhost,127.0.0.1
     DB_NAME=fiji_ferry_db
     DB_USER=root
     DB_PASSWORD=your_mysql_password
     DB_HOST=localhost
     DB_PORT=3306
     EMAIL_HOST=smtp.gmail.com
     EMAIL_PORT=587
     EMAIL_USE_TLS=True
     EMAIL_HOST_USER=your_email@gmail.com
     EMAIL_HOST_PASSWORD=your_app_password
     STRIPE_PUBLISHABLE_KEY=pk_test_...
     STRIPE_SECRET_KEY=sk_test_...
     STRIPE_WEBHOOK_SECRET=whsec_...
     WEATHER_API_KEY=your_weather_api_key
     ```
   - Replace:
     - `your_mysql_password`: MySQL root password
     - `your_email@gmail.com`, `your_app_password`: Gmail and app-specific password
     - `SECRET_KEY`: Generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`
     - API keys: Obtain from team lead or API dashboards

4. **Run Migrations**:
   - Activate virtual environment.
   - Generate: `python manage.py makemigrations`
   - Apply: `python manage.py migrate`
   - Verify: In Workbench, check `fiji_ferry_db` for tables (`auth_user`, `bookings_schedule`).

5. **Create Superuser**:
   - Run: `python manage.py createsuperuser`
   - Enter username (e.g., `admin`), email, and password.
   - Verify: Log in at `http://127.0.0.1:8000/admin/` after server start.

6. **Troubleshooting**:
   - Connection error: Verify MySQL server (`mysqladmin -u root -p status`), `DB_HOST`, `DB_PORT`.
   - Access denied: Check `DB_PASSWORD`. Reset in Workbench if needed.
   - No tables: Ensure `fiji_ferry_db` exists; rerun migrations.
   - SQLite fallback: Edit `settings.py` to use SQLite, then migrate.

### Step 6: Run Development Server

Start the server:

```bash
python manage.py runserver
```

- Visit: `http://127.0.0.1:8000/`
- Verify: Homepage shows slideshow, schedules, and weather data.
- **Troubleshooting**:
  - Page fails: Check `DEBUG=True` and server logs.
  - Weather missing: Verify `WEATHER_API_KEY`; check `/api/weather/` in browser console (F12).
  - Images missing: Ensure `static/images/` exists; run `python manage.py collectstatic` for production.

### Step 7: Access Admin Panel

- Visit: `http://127.0.0.1:8000/admin/`
- Log in with superuser credentials.
- Manage schedules, bookings, and users.
- **Troubleshooting**:
  - Login fails: Recreate superuser.
  - Blank page: Check server logs for template errors.

## Development Workflow

Use Agile methodology with sprints:

1. **Create Branch**:
   ```bash
   git checkout -b feature/feature-name
   ```
2. **Code and Test**:
   - Edit `accounts` or `bookings` apps.
   - Test: `python manage.py test`, `python manage.py runserver`
3. **Commit**:
   ```bash
   git add .
   git commit -m "Add: feature description"
   ```
4. **Push and Pull Request**:
   ```bash
   git push origin feature/feature-name
   ```
   - Create pull request on repository platform.

## Django Commands

- New app: `python manage.py startapp app_name`
- Migrations: `python manage.py makemigrations`, `python manage.py migrate`
- Superuser: `python manage.py createsuperuser`
- Tests: `python manage.py test`
- Static files: `python manage.py collectstatic`

## Project Structure

```
fiji_ferry_booking/
├── ferry_system/           # Core settings
│   ├── settings.py        # Django config
│   ├── urls.py           # URL routing
│   └── wsgi.py           # WSGI app
├── accounts/              # User management
│   ├── models.py         # User models
│   ├── views.py          # Auth views
│   └── admin.py          # Admin config
├── bookings/              # Booking logic
│   ├── models.py         # Booking models
│   ├── views.py          # Booking views
│   └── admin.py          # Admin config
├── templates/             # HTML templates
├── static/               # CSS, JS, images
├── media/                # Uploads (QR codes, documents)
├── requirements.txt      # Dependencies
├── .env                 # Environment variables
└── manage.py            # Management script
```

## Contributing

- Follow Agile sprints.
- Use feature branches.
- Write tests in `app/tests.py`.
- Update this README for major changes.
- Adhere to Django best practices (DRY, MVT separation).

## Team Members

| Student ID | Name                     |
|------------|--------------------------|
| S11210953  | Lagilava Paulo           |
| S11221892  | Pene Konousi             |
| S11223573  | Rigieta Nagera           |
| S11221570  | Sekove Koroi             |
| S11196578  | Kesaia Waqavakatoga      |

## License

Educational project for IS314 Course.