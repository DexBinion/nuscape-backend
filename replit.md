# Overview

NuScape is a cross-platform usage tracking application that monitors app and website usage across Windows, Mac, Android, and iOS devices. The system consists of a FastAPI backend that collects usage data from registered devices and a web dashboard for visualizing usage statistics. 

**Current Architecture:** Backend + Web Dashboard only. Client applications (desktop and mobile) will be built using Flutter by external developer team.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Backend Architecture (Production Ready)
The application uses a modern Python backend built with FastAPI, providing asynchronous request handling and automatic API documentation. The architecture follows a layered approach with clear separation of concerns:

- **API Layer**: FastAPI routes handle HTTP requests with automatic validation via Pydantic schemas
- **Business Logic Layer**: CRUD operations and authentication logic are separated into dedicated modules
- **Data Access Layer**: SQLAlchemy ORM with async support provides database abstraction

## Database Design
The system uses PostgreSQL with a simple two-table schema:
- **Devices table**: Stores registered devices with unique device keys for authentication
- **Usage logs table**: Records app usage sessions with start/end timestamps and duration

The schema uses UUID primary keys for better scalability and includes proper indexing on frequently queried fields (device_key, device_id, start timestamps).

## Authentication Strategy
A unified JWT-based authentication system is implemented for production security:
- Each device receives access and refresh JWT tokens upon registration 
- API endpoints use Bearer token validation with JWT signature verification
- 24-hour access tokens for API calls, 30-day refresh tokens for renewal
- Device revocation capability invalidates all tokens for security
- No user accounts or complex permission systems - focused on device-level access control
- Legacy device_key compatibility maintained for existing clients

## Frontend Architecture (Web Dashboard)
The dashboard is a lightweight single-page application built with vanilla JavaScript and Bootstrap:
- No heavy frontend frameworks to maintain simplicity
- Uses modern JavaScript features (async/await, fetch API)
- Responsive design with Bootstrap for cross-device compatibility
- Real-time data fetching with error handling and loading states

## Data Flow
1. Client apps register devices to receive authentication credentials
2. Client apps periodically submit batches of usage data via REST API
3. Web dashboard fetches aggregated statistics and displays visualizations
4. All database operations use async patterns for better performance

## API Design (Flutter Ready)
RESTful API with comprehensive endpoints for client integration:

### Device Management:
- `POST /api/v1/devices/register` - Register new device and receive JWT access/refresh tokens
- `GET /api/v1/devices` - List all registered devices
- `POST /api/v1/devices/refresh` - Refresh expired access tokens using refresh token
- `POST /api/v1/devices/revoke` - Revoke all tokens for a device (security)

### Usage Data:
- `POST /api/v1/usage/batch` - Upload usage data in batches (requires Bearer token)

### Statistics:
- `GET /api/v1/stats/today` - Get today's usage statistics
- `GET /api/v1/stats/week` - Get weekly usage statistics

### Health Check:
- `GET /health` - API health status

The API follows conventional HTTP status codes and JSON response formats, with comprehensive error handling and validation.

# External Dependencies

## Database
- **PostgreSQL**: Primary data storage with asyncpg driver for async operations
- **SQLAlchemy**: ORM with async support for database interactions
- **Alembic**: Database migration management tool

## Backend Framework
- **FastAPI**: Modern async web framework with automatic OpenAPI documentation
- **Uvicorn**: ASGI server for production deployment
- **Pydantic**: Data validation and serialization

## Frontend Dependencies
- **Bootstrap 5.3.0**: CSS framework via CDN for responsive UI components
- **Font Awesome 6.4.0**: Icon library via CDN for UI elements
- **Vanilla JavaScript**: Uses modern JS features to minimize complexity

## Development Tools
- **Alembic**: Database schema versioning and migrations
- Custom seed script for development data population

## Environment Configuration
- **DATABASE_URL**: PostgreSQL connection string (required)
- **API_BASE_PATH**: API route prefix (optional, defaults to /api/v1)

## CORS Configuration
Configured to accept requests from any origin for development, with plans to restrict to specific origins in production environments.

# Client Application Integration

## Flutter Development (External Team)
The client applications will be developed using Flutter to provide:

### Desktop Apps (Windows/macOS):
- Background usage tracking services
- System tray/menu bar integration
- Native system APIs for process monitoring
- Automatic data synchronization with backend

### Mobile Apps (Android/iOS):
- Native usage statistics access (UsageStatsManager on Android)
- Background data collection services
- Real-time sync with backend API
- Cross-platform consistency

### Integration Points:
- **Device Registration**: Use `POST /api/v1/devices/register` endpoint
- **Data Upload**: Use `POST /api/v1/usage/batch` for periodic sync
- **Authentication**: JWT-based Bearer token system with refresh capability

# Current Project Structure

```
NuScape/
├── backend/           # FastAPI backend application
├── static/            # Web dashboard (HTML, CSS, JS)
├── alembic/          # Database migrations
├── dev/              # Development utilities and seed data
├── main.py           # FastAPI application entry point
├── alembic.ini       # Alembic configuration
└── replit.md         # This documentation
```

# Deployment Information

- **Backend URL**: https://nu-scape-tracker-dexterjk86.replit.app/
- **Web Dashboard**: https://nu-scape-tracker-dexterjk86.replit.app/
- **API Documentation**: https://nu-scape-tracker-dexterjk86.replit.app/docs
- **Database**: PostgreSQL (managed by Replit)
- **Environment**: Production ready with auto-scaling

# Development Handoff Notes

The backend and web dashboard are production-ready. The API is fully documented and tested. External Flutter development team can immediately begin client application development using the existing API endpoints.

All authentication, data validation, and database management is handled by the backend. Client applications need only to implement usage tracking and periodic data synchronization.