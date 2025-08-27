Fiji Ferry Booking System - IS314 Project
Team: Group 10Supervisor: Mr. Ravneil NandSemester: 2, 2025
Project Description
The Fiji Ferry Booking System is a web-based platform designed to streamline ferry travel across Fiji. It enables users to book and pay for ferry tickets, view real-time schedules, and manage bookings, reducing reliance on physical ticket counters. The system enhances transportation accessibility for residents in suburbs, interiors, and outer islands.
Key Features

Online Ticket Booking: Select routes, dates, and passenger numbers.
Digital Payments: Secure payments via Stripe.
Real-Time Schedules: Live updates on ferry schedules and seat availability.
QR Code Ticketing: Scannable QR codes for tickets and cargo.
Booking Management: View booking history and cancel bookings online.
Weather Updates: Real-time weather data for routes (e.g., "Patchy rain nearby, 25°C, Wind 29.5kph").

Technology Stack

Backend: Python, Django
Database: MySQL (SQLite for development)
Frontend: HTML, CSS, JavaScript
External APIs: WeatherAPI, Stripe
Development Methodology: Agile

Setup Instructions
These instructions guide you through setting up the project locally using MySQL Workbench. They are designed to be beginner-friendly with clear steps and troubleshooting tips.
Step 1: Install Prerequisites
Ensure the following tools are installed before proceeding. Verify each installation to avoid issues.

Python 3.8+:

Download from python.org.
Verify: Run python --version (Windows) or python3 --version (Mac/Linux) in a terminal. Ensure the version is 3.8 or higher.
Troubleshooting: If not installed, download the latest version and add Python to your system PATH during installation.


Git:

Download from git-scm.com.
Verify: Run git --version in a terminal.
Troubleshooting: If not found, install Git and ensure it’s added to PATH.


MySQL and MySQL Workbench:

Download MySQL Community Server and Workbench from mysql.com.
Start MySQL Server:
Windows: Use MySQL Installer to start the server.
Mac: Install via Homebrew (brew install mysql) and start with brew services start mysql.
Linux: Install with sudo apt-get install mysql-server (Ubuntu) and start with sudo service mysql start.


Verify: Open MySQL Workbench, connect to localhost (port 3306) with username root and your password.
Troubleshooting:
If connection fails, ensure MySQL Server is running (mysqladmin -u root -p status).
Reset password if needed: In Workbench, run ALTER USER 'root'@'localhost' IDENTIFIED BY 'new_password';.




MySQL Client Library:

Install mysqlclient for Django-MySQL integration:pip install mysqlclient


Troubleshooting:
If you get mysql_config not found:
Windows: Install MySQL Connector/C via MySQL Installer.
Mac: Run brew install mysql-connector-c.
Linux: Run sudo apt-get install libmysqlclient-dev (Ubuntu).


Ensure pip is for Python 3 (pip --version should show Python 3.x).





Step 2: Clone the Repository

Clone the project:
git clone <repository-url>
cd fiji_ferry_booking


Replace <repository-url> with the actual URL (e.g., from GitHub or Bitbucket).
Verify: Check that the fiji_ferry_booking directory contains manage.py and requirements.txt.


Troubleshooting:

If cloning fails, verify Git is installed and the URL is correct.
Ensure you have repository access (check with team lead if using private repo).



Step 3: Set Up Virtual Environment
Isolate project dependencies using a virtual environment.

Create and activate:
Windows:python -m venv venv
venv\Scripts\activate


Mac/Linux:python3 -m venv venv
source venv/bin/activate




Verify: The terminal prompt should show (venv). Run pip --version to confirm it’s using the virtual environment’s pip.
Troubleshooting:
If activation fails, ensure Python is installed and the venv command matches your Python version (python or python3).
If pip commands fail, ensure the virtual environment is activated.



Step 4: Install Dependencies
Install required Python packages:
pip install -r requirements.txt


This installs Django, mysqlclient, stripe, requests, celery, and other dependencies.
Verify: Run pip list to confirm all packages from requirements.txt are installed.
Troubleshooting:
If installation fails, check for mysqlclient issues (see Step 1).
Ensure requirements.txt matches the provided version (includes celery==5.4.0).
If errors persist, try pip install --force-reinstall -r requirements.txt.



Step 5: Configure MySQL Database
Set up the fiji_ferry_db database using MySQL Workbench.

Launch MySQL Workbench:

Open Workbench and connect to localhost (port 3306, username root, password from MySQL setup).
Verify: Click “Test Connection” to ensure it connects successfully.


Create Database:

Open a new query tab (File > New Query Tab).
Run:CREATE DATABASE fiji_ferry_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;


Verify: Run SHOW DATABASES; and confirm fiji_ferry_db appears in the Schemas panel.


Configure Environment Variables:

Copy the example .env file:cp .env.example .env


Edit .env with a text editor (e.g., VS Code):SECRET_KEY=your-secret-key-here-change-this-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=fiji_ferry_db
DB_USER=root
DB_PASSWORD=your_mysql_root_password
DB_HOST=localhost
DB_PORT=3306
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_email_app_password
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
WEATHER_API_KEY=your_weather_api_key


Replace:
your_mysql_root_password: Your MySQL root password.
your_email@gmail.com and your_email_app_password: A Gmail account and app-specific password (generate at Google Account Settings).
SECRET_KEY: Generate a secure key with python -c "import secrets; print(secrets.token_urlsafe(50))".
Stripe and WeatherAPI keys: Obtain from team lead or respective API dashboards.




Run Migrations:

Ensure the virtual environment is activated.
Generate migrations:python manage.py makemigrations


Apply migrations:python manage.py migrate


Verify: In Workbench, refresh the Schemas panel, select fiji_ferry_db, and confirm tables like auth_user, bookings_schedule, and bookings_booking exist.


Create Superuser:

Create an admin user:python manage.py createsuperuser


Follow prompts (e.g., username: admin, email: admin@fijiferry.com, password: secure password).
Verify: Log in at http://127.0.0.1:8000/admin/ after starting the server.


Troubleshooting:

“Can’t connect to MySQL server”: Ensure MySQL Server is running (mysqladmin -u root -p status) and DB_HOST=localhost, DB_PORT=3306 in .env.
“Access denied for user ‘root’”: Verify DB_PASSWORD matches MySQL password. Reset if needed in Workbench.
“Table ‘django_migrations’ doesn’t exist”: Run python manage.py migrate.
No tables created: Check migration output for errors and ensure fiji_ferry_db exists.
Fallback to SQLite: For development, edit settings.py to use SQLite (uncomment SQLite block, comment MySQL block), then run python manage.py migrate.



Step 6: Run the Development Server

Start the server:python manage.py runserver


Open http://127.0.0.1:8000/ in a browser.
Verify:
Homepage loads with hero slideshow, schedule cards, and weather data (e.g., “Patchy rain nearby, 25°C”).
Fiji map displays clickable markers (Nadi, Suva, etc.).


Troubleshooting:
Page doesn’t load: Ensure DEBUG=True in .env. Check terminal for errors.
Weather data missing: Verify WEATHER_API_KEY in .env. Check browser console (F12 > Console) for /api/weather/ errors.
Images not loading: Ensure static/images/ contains slideshow images. Run python manage.py collectstatic for production.



Step 7: Access the Admin Panel

Visit http://127.0.0.1:8000/admin/.
Log in with superuser credentials (Step 5).
Use the panel to manage schedules, bookings, and users.
Troubleshooting:
Login fails: Verify superuser credentials. Recreate with python manage.py createsuperuser.
Admin page blank: Check server logs for template errors.



Development Workflow
Adopt Agile methodology with sprints for feature development.

Create Feature Branch:git checkout -b feature/feature-name


Develop and Test:
Write code in accounts or bookings apps.
Test locally:python manage.py test
python manage.py runserver




Commit Changes:git add .
git commit -m "Add: feature description"


Push and Create Pull Request:git push origin feature/feature-name


Create a pull request on the repository platform.



Common Django Commands

Start a new app: python manage.py startapp app_name
Generate migrations: python manage.py makemigrations
Apply migrations: python manage.py migrate
Create superuser: python manage.py createsuperuser
Run tests: python manage.py test
Collect static files: python manage.py collectstatic

Project Structure
fiji_ferry_booking/
├── ferry_system/           # Project settings
│   ├── settings.py        # Django configuration
│   ├── urls.py           # Main URL routing
│   └── wsgi.py           # WSGI application
├── accounts/              # User management app
│   ├── models.py         # User models
│   ├── views.py          # Authentication views
│   └── admin.py          # Admin configuration
├── bookings/              # Ferry booking app
│   ├── models.py         # Booking models
│   ├── views.py          # Booking logic
│   └── admin.py          # Admin configuration
├── templates/             # HTML templates
├── static/               # CSS, JS, images
├── media/                # User uploads (e.g., QR codes, documents)
├── requirements.txt      # Python dependencies
├── .env                 # Environment variables
└── manage.py            # Django management script

Contributing

Follow Agile practices with regular sprints.
Create feature branches for new functionality.
Write tests (app/tests.py) for new features.
Update this README for significant changes.
Follow Django best practices (DRY, model-view-template separation).

Team Members



Student ID
Name



S11210953
Lagilava Paulo


S11221892
Pene Konousi


S11223573
Rigieta Nagera


S11221570
Sekove Koroi


S11196578
Kesaia Waqavakatoga


License
This project is for educational purposes as part of the IS314 Course Project.