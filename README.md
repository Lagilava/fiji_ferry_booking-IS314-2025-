# Fiji Ferry Booking System - IS314 Project

**Team**: Group 10  
**Supervisor**: Mr Ravneil Nand  
**Semester**: 2 2025

## Project Description

The Fiji Ferry Booking Website is an online platform designed to simplify ferry travel across Fiji. It allows users to book and pay for ferry tickets, view real-time schedules, and manage bookings, replacing the reliance on physical ticket counters. The system serves residents in suburbs, interiors, and outer islands, enhancing transportation accessibility.

## Key Features

1. **Online Ticket Booking**: Select routes, dates, and passenger numbers.
2. **Digital Payment Integration**: Secure online payments via Stripe.
3. **Real-Time Schedule Updates**: Live ferry schedules and seat availability.
4. **QR Code Ticketing**: Scannable QR codes for tickets.
5. **Booking History and Cancellation**: Manage bookings online.
6. **Weather Updates**: Displays real-time weather for routes (e.g., "Patchy rain nearby, 25°C, Wind 29.5kph").

## Technology Stack

- **Backend**: Python Django
- **Database**: MySQL (SQLite for development)
- **Frontend**: HTML, CSS, JavaScript
- **External APIs**: WeatherAPI, OpenWeatherMap, Stripe
- **Development Methodology**: Agile Development

## Setup Instructions

Follow these steps to set up the project locally using MySQL Workbench for the database. The instructions are beginner-friendly and include troubleshooting tips.

### Step 1: Prerequisites

1. **Python 3.8+**:
   - Download and install from [python.org](https://www.python.org/downloads/).
   - Verify: `python --version` (Windows) or `python3 --version` (Mac/Linux).

2. **Git**:
   - Download and install from [git-scm.com](https://git-scm.com/downloads).
   - Verify: `git --version`.

3. **MySQL Workbench**:
   - Download and install MySQL Community Server and Workbench from [mysql.com](https://www.mysql.com/products/community/).
   - Ensure MySQL Server is running (default port: 3306).
     - **Windows**: Use MySQL Installer to start the server.
     - **Mac**: `brew install mysql` (Homebrew) and `brew services start mysql`.
     - **Linux**: `sudo apt-get install mysql-server` (Ubuntu) and `sudo service mysql start`.
   - Verify: Open MySQL Workbench and connect to `localhost` with username `root` and your password.

4. **MySQL Client Library**:
   - Install `mysqlclient` for Django to connect to MySQL:
     ```bash
     pip install mysqlclient
     ```
   - If errors occur (e.g., `mysql_config not found`), install MySQL development libraries:
     - **Windows**: Install MySQL Connector/C via MySQL Installer.
     - **Mac**: `brew install mysql-connector-c` (Homebrew).
     - **Linux**: `sudo apt-get install libmysqlclient-dev` (Ubuntu).

### Step 2: Clone the Repository

Clone the project repository and navigate to the project directory:

```bash
git clone <repository-url>
cd fiji_ferry_booking

Replace <repository-url> with the actual repository URL (e.g., from GitHub or Bitbucket).
Step 3: Create and Activate Virtual Environment
Create a virtual environment to isolate project dependencies.
Windows:
python -m venv venv
venv\Scripts\activate

Mac/Linux:
python3 -m venv venv
source venv/bin/activate

Verify the virtual environment is activated (you’ll see (venv) in the terminal prompt).
Step 4: Install Dependencies
Install the required Python packages:
pip install -r requirements.txt

This installs Django, mysqlclient, and other dependencies listed in requirements.txt.
Step 5: Database Setup (MySQL with Workbench)
The project uses MySQL as the default database. Follow these steps to set up the database using MySQL Workbench.
Prerequisites

MySQL Server is running (port: 3306).
MySQL Workbench is installed.
mysqlclient is installed (see Step 1).

Instructions

Launch MySQL Workbench:

Open MySQL Workbench.
Connect to your local MySQL server:
Click the “Local Instance MySQL” tile or create a new connection:
Connection Name: FijiFerryDB
Hostname: localhost
Port: 3306
Username: root
Password: <your_root_password> (set during MySQL installation)


Click “Test Connection” to confirm it works. Enter your password if prompted.




Create the Database:

In MySQL Workbench, open a new query tab (File > New Query Tab).
Run this SQL command to create the database:CREATE DATABASE fiji_ferry_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;


This creates a database named fiji_ferry_db with proper encoding for Django.


Verify the database exists:SHOW DATABASES;


You should see fiji_ferry_db in the list under the Schemas panel.




Configure Environment Variables:

Copy the example environment file:cp .env.example .env


Open .env in a text editor (e.g., VS Code or Notepad) and update the database settings:SECRET_KEY=your-secret-key-here-change-this-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,96aa1cab46a1.ngrok-free.app
DB_NAME=fiji_ferry_db
DB_USER=root
DB_PASSWORD=your_mysql_root_password
DB_HOST=localhost
DB_PORT=3306
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_email_password
STRIPE_PUBLIC_KEY=pk_test_51RsEOGE00EqGlVqe6bQrzzRx8iRLvFfsEW0GatUEn0bcixeQ8OwuKbDroXiWBqasiNJBx05WMs2HQIUAkOYTMvSM00Ar1TuTii
STRIPE_SECRET_KEY=sk_test_51RsEOGE00EqGlVqeiMuIL6cybH13OLLXymW6zTAw2vbazH1XScBgfSs1tGc1F3AmnSZP8crAi3dsTlM9EKvzmonp00CG1i73O5
STRIPE_PUBLISHABLE_KEY=pk_test_51RsEOGE00EqGlVqe6bQrzzRx8iRLvFfsEW0GatUEn0bcixeQ8OwuKbDroXiWBqasiNJBx05WMs2HQIUAkOYTMvSM00Ar1TuTii
STRIPE_WEBHOOK_SECRET=whsec_ZPQRcvxYL6aGC0DhTRaZIjnxcbODTqPj


Replace your_mysql_root_password with the password used in MySQL Workbench.
Replace your_email@gmail.com and your_email_password with a valid Gmail account and app-specific password for email functionality.
Generate a secure SECRET_KEY (e.g., using python -c "import secrets; print(secrets.token_urlsafe(50))") for production.




Run Migrations:

Ensure the virtual environment is activated.
Generate migration files for the accounts and bookings apps:python manage.py makemigrations


Apply migrations to create database tables:python manage.py migrate


Verify in MySQL Workbench:
Refresh the Schemas panel.
Select fiji_ferry_db and confirm tables like auth_user, bookings_schedule, bookings_booking, and accounts_user exist.




Create a Superuser:

Create an admin user for the Django admin panel:python manage.py createsuperuser


Follow prompts to enter:
Username: e.g., admin
Email: e.g., admin@fijiferry.com
Password: Choose a secure password




This user is used to access the admin panel.



Troubleshooting

“Can’t connect to MySQL server on ‘localhost’ (10061)”:
Ensure MySQL Server is running: In MySQL Workbench, check the server status or run mysqladmin -u root -p status.
Verify DB_HOST=localhost and DB_PORT=3306 in .env.


“Access denied for user ‘root’”:
Confirm DB_PASSWORD in .env matches your MySQL root password.
Reset the password in MySQL Workbench:ALTER USER 'root'@'localhost' IDENTIFIED BY 'new_password';

Update DB_PASSWORD=new_password in .env.


“mysqlclient not found”:
Install mysqlclient: pip install mysqlclient.
Ensure MySQL development libraries are installed (see Step 1).


“Table ‘fiji_ferry_db.django_migrations’ doesn’t exist”:
Run python manage.py migrate to create necessary tables.


No tables created:
Check for errors in python manage.py migrate output.
Ensure fiji_ferry_db exists (SHOW DATABASES; in Workbench).



Note: For development only, you can switch to SQLite by commenting out the MySQL DATABASES block in settings.py and uncommenting the SQLite configuration. Then run python manage.py migrate.
Step 6: Run Development Server
Start the Django development server:
python manage.py runserver


Open a browser and visit: http://127.0.0.1:8000/
Verify the homepage loads, showing:
Hero slideshow with lazy-loaded images.
Schedule cards with weather data (e.g., “Patchy rain nearby, 25°C, Wind 29.5kph” with 🌧️).
Fiji map with clickable markers (Nadi, Suva, Taveuni, Savusavu).



Step 7: Access Admin Panel

Visit: http://127.0.0.1:8000/admin/
Log in with the superuser credentials created in Step 5.
Use the admin panel to manage ferry schedules, bookings, and users.

Troubleshooting Server Issues

Page doesn’t load:
Ensure DEBUG=True in .env.
Check terminal for errors (e.g., missing dependencies, database issues).


Weather data missing:
Verify WEATHER_API_KEY and OPENWEATHERMAP_API_KEY in settings.py.
Open browser console (F12 > Console) and check for /api/weather/ errors.


Images not loading:
Ensure static/images/ contains hero slideshow images.
Run python manage.py collectstatic if in production.



Development Workflow
Follow Agile methodology for developing new features.
Creating New Features

Create Feature Branch:
git checkout -b feature/feature-name


Make Changes and Test:

Write code in the appropriate app (accounts or bookings).
Test locally:python manage.py test
python manage.py runserver




Commit Changes:
git add .
git commit -m "Add: feature description"


Push and Create Pull Request:
git push origin feature/feature-name


Create a pull request on the repository platform (e.g., GitHub).



Common Django Commands

Create a new app:python manage.py startapp app_name


Generate migrations after model changes:python manage.py makemigrations


Apply migrations:python manage.py migrate


Create superuser:python manage.py createsuperuser


Run tests:python manage.py test


Collect static files (for production):python manage.py collectstatic



Project Structure
fiji_ferry_booking/
├── ferry_system/           # Main project settings
│   ├── settings.py        # Django configuration
│   ├── urls.py           # Main URL routing
│   └── wsgi.py           # WSGI application
├── accounts/              # User management app
│   ├── models.py         # User-related models
│   ├── views.py          # Authentication views
│   └── admin.py          # Admin configuration
├── bookings/              # Ferry booking app
│   ├── models.py         # Booking-related models
│   ├── views.py          # Booking logic
│   └── admin.py          # Admin configuration
├── templates/             # HTML templates
├── static/               # CSS, JS, images
├── media/                # User uploads
├── requirements.txt      # Python dependencies
├── .env                  # Environment variables
└── manage.py            # Django management script

Contributing

Follow Agile methodology with regular sprints.
Create feature branches for new functionality.
Write tests for new features (place in app/tests.py).
Update documentation (e.g., this README) as needed.
Follow Django best practices (e.g., DRY, model-view-template separation).

Team Members

[Add team member names and roles here]

License
This project is for educational purposes as part of the IS314 Course Project.```