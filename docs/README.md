# Fingerprint Time Logger Documentation

**Version**: 2.0  
**Last Updated**: January 2025

## Overview

This directory contains comprehensive documentation for the Fingerprint Time Logger system. The documentation is organized to help different user types find the information they need quickly and efficiently.

## 📚 Documentation Structure

### For Users
- **[Quick Start Guide](../QUICK_START.md)** - Get up and running in minutes
- **[User Manual](USER_MANUAL.md)** - Complete user guide (coming soon)
- **[FAQ](FAQ.md)** - Frequently asked questions (coming soon)

### For Administrators
- **[Deployment Guide](DEPLOYMENT_GUIDE.md)** - Production deployment instructions
- **[System Architecture](SYSTEM_ARCHITECTURE.md)** - Technical architecture overview
- **[Troubleshooting](TROUBLESHOOTING.md)** - Common issues and solutions

### For Developers
- **[Developer Guide](DEVELOPER_GUIDE.md)** - Complete development guide
- **[API Reference](API_REFERENCE.md)** - Comprehensive API documentation
- **[Database Schema](../database/database_schema.md)** - Database structure and relationships

### Project Information
- **[Changelog](CHANGELOG.md)** - Version history and changes
- **[Contributing](CONTRIBUTING.md)** - How to contribute (coming soon)
- **[License](LICENSE.md)** - License information (coming soon)

## 🚀 Quick Navigation

### Getting Started
1. **New to the system?** Start with the [Quick Start Guide](../QUICK_START.md)
2. **Setting up for development?** Read the [Developer Guide](DEVELOPER_GUIDE.md)
3. **Deploying to production?** Follow the [Deployment Guide](DEPLOYMENT_GUIDE.md)

### Common Tasks
- **API Integration**: See [API Reference](API_REFERENCE.md)
- **Database Changes**: Check [Database Schema](../database/database_schema.md)
- **System Issues**: Refer to [Troubleshooting](TROUBLESHOOTING.md)
- **Understanding Architecture**: Review [System Architecture](SYSTEM_ARCHITECTURE.md)

## 📖 Documentation Standards

### Writing Guidelines
- Use clear, concise language
- Include code examples where appropriate
- Maintain consistent formatting
- Update documentation with code changes
- Test all provided examples

### Structure
- Start with overview and purpose
- Include table of contents for long documents
- Use headings for easy navigation
- Provide examples and use cases
- Include troubleshooting sections

### Code Examples
- Use syntax highlighting
- Include complete, runnable examples
- Explain complex code blocks
- Show both request and response examples
- Include error handling examples

## 🛠️ Current System Status

### System Overview
The Fingerprint Time Logger is a modern, streamlined system designed for single-user installations. After the major 2.0 release in January 2025, the system features:

- **Unified Architecture**: Single FastAPI process handling all functionality
- **Real-time Updates**: WebSocket-based live dashboard updates
- **Auto-Import**: Background synchronization every 30 minutes
- **Comprehensive Monitoring**: Health checks and system diagnostics
- **Thai Localization**: Full support for Thai employee names

### Key Features
✅ **ZKTeco Device Integration** - Direct fingerprint device communication  
✅ **Employee Management** - Unified employee records with Thai/English names  
✅ **Attendance Tracking** - Real-time punch data collection and display  
✅ **System Monitoring** - Health checks, diagnostics, and performance metrics  
✅ **Data Export** - CSV export with flexible filtering options  
✅ **Background Tasks** - Automated data synchronization  

### Recent Improvements (v2.0)
- **35% code reduction** through cleanup of unused functionality
- **Unified employee model** consolidating separate name tables
- **Enhanced monitoring** with comprehensive health checks
- **Improved performance** with streamlined architecture
- **Better documentation** with comprehensive guides and references

## 🔧 Technical Stack

### Backend
- **FastAPI 0.104.1** - Modern web framework
- **SQLAlchemy 2.0.23** - Database ORM
- **Alembic 1.12.1** - Database migrations
- **pyzk 0.9** - ZKTeco device communication
- **SQLite** - Local database storage

### Frontend
- **HTML5/CSS3/JavaScript** - Modern web standards
- **WebSocket** - Real-time updates
- **Responsive Design** - Mobile-friendly interface
- **Thai Font Support** - Proper Thai text rendering

### Infrastructure
- **Uvicorn** - ASGI server
- **Python 3.8+** - Runtime environment
- **Systemd** - Service management
- **Docker** - Containerization support

## 📊 API Overview

The system provides a comprehensive REST API organized into logical modules:

### Core APIs
- **`/api/attendance/`** - Attendance record management
- **`/api/devices/`** - Device connectivity and management
- **`/api/employees/`** - Employee data and Thai name management
- **`/api/export/`** - Data export functionality
- **`/api/system/`** - System health and monitoring

### Real-time Features
- **WebSocket endpoint** (`/ws`) for live updates
- **Auto-sync notifications** for device time synchronization
- **Live dashboard updates** for attendance changes
- **System health monitoring** with real-time status

For complete API documentation, see the [API Reference](API_REFERENCE.md).

## 🗃️ Database Schema

### Core Tables
- **`devices`** - ZKTeco device configuration
- **`employees`** - Unified employee records (post-2.0 consolidation)
- **`attendance_records`** - Time punch data with sync status
- **`job_roles`** - Employee role definitions

### Key Relationships
- Employees linked to attendance records via badge number
- Devices associated with attendance records
- Job roles optionally assigned to employees
- Unified employee model eliminates previous dual-table structure

For detailed schema information, see [Database Schema](../database/database_schema.md).

## 🔍 Troubleshooting

### Common Issues
1. **Device Connection Problems**
   - Check network connectivity to ZKTeco device
   - Verify device IP address and port configuration
   - Review device-specific logs in system monitoring

2. **Database Issues**
   - Ensure SQLite file permissions are correct
   - Run database integrity checks
   - Check available disk space

3. **Performance Issues**
   - Monitor system resource usage
   - Review database query performance
   - Check background task execution

For detailed troubleshooting guides, see [Troubleshooting](TROUBLESHOOTING.md).

## 📝 Contributing

We welcome contributions to improve the system and documentation. When contributing:

1. **Code Changes**: Follow the development guidelines in [Developer Guide](DEVELOPER_GUIDE.md)
2. **Documentation**: Update relevant documentation with code changes
3. **Testing**: Ensure all tests pass and add new tests for new features
4. **Commit Messages**: Follow the format described in [Changelog](CHANGELOG.md)

## 🆘 Support

### Getting Help
1. **Documentation**: Check this documentation first
2. **Troubleshooting**: Review common issues and solutions
3. **Logs**: Check system logs for error messages
4. **Health Checks**: Use built-in health monitoring endpoints

### Support Resources
- **System Logs**: `/opt/fingerprint-logger/logs/`
- **Health Endpoints**: `/health`, `/api/system/health`
- **Status Dashboard**: `/status`
- **API Documentation**: Available at `/docs` (when running)

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE.md) file for details.

## 🔄 Version Information

- **Current Version**: 2.0.0
- **Release Date**: January 9, 2025
- **Compatibility**: Python 3.8+, SQLite 3.35+
- **Dependencies**: See `requirements.txt`

For version history and changes, see the [Changelog](CHANGELOG.md).

---

## Legacy Documentation

The following legacy documentation is maintained for reference:

### Essential Docs
- `POC_RESULTS.md` - ZKTeco device integration proof of concept
- `DOCUMENTATION.md` - Comprehensive user/developer guide  
- `TECHNICAL_REFERENCE.md` - Implementation details

### Archive
Detailed implementation docs moved to `archive/` for reference.

---

*This documentation is actively maintained and updated with each release. For the most current information, always refer to the documentation in the latest version.*