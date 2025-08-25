# Fiji Ferry Booking System - IS314 Project

**Team**: Group 10  
**Supervisor**: Mr Ravneil Nand  
**Semester**: 2 2025

## Project Description

The Fiji Ferry Booking Website aims to revolutionize transportation accessibility across Fiji by providing an efficient online platform for booking and paying for ferry tickets. This system addresses the current reliance on physical ticket counters and serves residents in suburbs, interiors, and outer islands.

## Key Features

1. **Online Ticket Booking** - Select routes, dates, and passenger numbers
2. **Digital Payment Integration** - Secure online payments
3. **Real-Time Schedule Updates** - Live ferry schedules and availability
4. **QR Code Ticketing** - Scannable QR codes for tickets
5. **Booking History and Cancellation** - Manage bookings online

## Technology Stack

- **Backend**: Python Django
- **Database**: MySQL (SQLite for development)
- **Frontend**: HTML, CSS, JavaScript
- **Development Methodology**: Agile Development

## Setup Instructions

### Prerequisites

1. **Python 3.8+** - Download from [python.org](https://python.org)
2. **Git** - Download from [git-scm.com](https://git-scm.com)
3. **MySQL** (Optional for production) - Download from [mysql.com](https://mysql.com)

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd fiji_ferry_booking
```

### Step 2: Create Virtual Environment

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Environment Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` file with your settings:
   ```
   SECRET_KEY=your-secret-key-here
   DEBUG=True
   DB_PASSWORD=your_mysql_password
   EMAIL_HOST_USER=your_email@gmail.com
   EMAIL_HOST_PASSWORD=your_email_password
   ```

### Step 5: Database Setup

**For Development (SQLite - Default):**
```bash
python manage.py migrate
python manage.py createsuperuser
```

**For Production (MySQL):**
1. Create MySQL database:
   ```sql
   CREATE DATABASE fiji_ferry_db;
   ```
2. Update `.env` with MySQL credentials
3. Uncomment MySQL configuration in `settings.py`
4. Run migrations:
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   ```

### Step 6: Run Development Server

```bash
python manage.py runserver
```

Visit: http://127.0.0.1:8000/

### Step 7: Access Admin Panel

Visit: http://127.0.0.1:8000/admin/
Login with superuser credentials created in Step 5.

## Development Workflow

### Creating New Features (Agile)

1. **Create Feature Branch:**
   ```bash
   git checkout -b feature/feature-name
   ```

2. **Make Changes and Test:**
   ```bash
   python manage.py test
   python manage.py runserver
   ```

3. **Commit Changes:**
   ```bash
   git add .
   git commit -m "Add: feature description"
   ```

4. **Push and Create Pull Request:**
   ```bash
   git push origin feature/feature-name
   ```

### Common Django Commands

```bash
# Create new app
python manage.py startapp app_name

# Make migrations after model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run tests
python manage.py test

# Collect static files (for production)
python manage.py collectstatic
```

## Project Structure

```
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
```

## Contributing

1. Follow Agile methodology with regular sprints
2. Create feature branches for new functionality
3. Write tests for new features
4. Update documentation as needed
5. Follow Django best practices

## Team Members

- [Add team member names and roles]

## License

This project is for educational purposes - IS314 Course Project.
