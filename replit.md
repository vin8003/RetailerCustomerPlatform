# Ordering Platform

## Overview

The ordering platform is a comprehensive Django-based e-commerce solution that connects retailers with customers through a structured ordering system. The platform facilitates product catalog management, order processing, and customer-retailer interactions with distinct user roles and functionalities.

## System Architecture

### Backend Architecture
- **Framework**: Django 4.x with Django REST Framework
- **Database**: Configurable (currently using Django's default database setup)
- **Authentication**: JWT-based authentication using Simple JWT with custom user model
- **API Design**: RESTful API architecture with proper HTTP methods and status codes
- **File Storage**: Django's default file storage system for media files

### User Management
- **Custom User Model**: Extended AbstractUser with user_type field supporting 'retailer' and 'customer' roles
- **Phone-based Authentication**: OTP verification system for customer registration
- **Role-based Access Control**: Distinct permissions for retailers and customers

### Application Structure
The system follows Django's app-based architecture with the following apps:
- `authentication`: User management and authentication
- `retailers`: Retailer profile and business management
- `customers`: Customer profile and preferences
- `products`: Product catalog and inventory management
- `orders`: Order processing and lifecycle management
- `cart`: Shopping cart functionality
- `common`: Shared utilities and permissions

## Key Components

### Authentication System
- **JWT Token Management**: Access and refresh token system
- **OTP Verification**: Phone number verification using TOTP
- **User Registration**: Separate flows for retailers and customers
- **Session Management**: User session tracking and management

### Retailer Management
- **Business Profiles**: Complete retailer information including shop details, contact info, and location
- **Operating Hours**: Configurable business hours for different days
- **Service Configuration**: Delivery and pickup options with radius and minimum order settings
- **Category Management**: Retailer categorization system

### Product Management
- **Catalog System**: Comprehensive product management with categories and brands
- **Inventory Tracking**: Stock management with minimum/maximum order quantities
- **Image Management**: Multiple product images with primary image selection
- **Bulk Upload**: Excel-based product import functionality

### Order Processing
- **Order Lifecycle**: Complete order management from placement to delivery
- **Status Tracking**: Detailed order status logs and updates
- **Delivery Options**: Support for both delivery and pickup modes
- **Payment Integration**: Cash on delivery/pickup payment modes

### Shopping Cart
- **Multi-retailer Support**: Separate carts for different retailers
- **Real-time Updates**: Cart validation and price calculations
- **Persistence**: Cart data persistence across sessions

## Data Flow

### User Registration Flow
1. User provides registration details
2. System creates user account based on user_type
3. For customers: OTP verification via phone
4. Profile creation and activation

### Order Processing Flow
1. Customer adds products to cart
2. Cart validation and total calculation
3. Order placement with delivery/pickup selection
4. Order confirmation and status updates
5. Order fulfillment and delivery tracking

### Product Management Flow
1. Retailer creates/updates product catalog
2. Inventory management and stock updates
3. Product availability validation
4. Customer product discovery and browsing

## External Dependencies

### Core Dependencies
- **Django**: Web framework
- **Django REST Framework**: API development
- **Simple JWT**: JWT authentication
- **CORS Headers**: Cross-origin resource sharing
- **Django Filters**: API filtering capabilities
- **Pillow**: Image processing
- **PyOTP**: OTP generation and verification
- **Pandas**: Excel file processing

### Optional Integrations
- **SMS API**: For OTP delivery (configurable)
- **Payment Gateways**: Future integration support
- **Email Services**: For notifications

## Deployment Strategy

### Environment Configuration
- **Settings Management**: Environment-based configuration
- **Debug Mode**: Configurable for development/production
- **Static Files**: Django's collectstatic for production
- **Media Files**: Configurable media storage

### Database Setup
- **Migrations**: Django's migration system for database schema
- **Indexes**: Optimized database indexes for performance
- **Relationships**: Proper foreign key relationships and constraints

### Security Considerations
- **Authentication**: JWT-based secure authentication
- **Permissions**: Role-based access control
- **Data Validation**: Comprehensive input validation
- **Rate Limiting**: Throttling for sensitive endpoints

## Changelog

```
Changelog:
- July 08, 2025. Initial setup
```

## User Preferences

```
Preferred communication style: Simple, everyday language.
```