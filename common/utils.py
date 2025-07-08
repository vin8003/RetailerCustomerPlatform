import os
import uuid
from datetime import datetime
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.text import slugify
from PIL import Image
import logging

logger = logging.getLogger(__name__)


def generate_upload_path(instance, filename):
    """
    Generate upload path for files based on model and instance
    """
    # Get file extension
    ext = filename.split('.')[-1].lower()
    
    # Generate unique filename
    unique_filename = f"{uuid.uuid4().hex}.{ext}"
    
    # Determine upload directory based on model
    model_name = instance.__class__.__name__.lower()
    
    # Create directory structure
    upload_dir = os.path.join(
        'uploads',
        model_name,
        datetime.now().strftime('%Y/%m/%d')
    )
    
    return os.path.join(upload_dir, unique_filename)


def generate_product_image_path(instance, filename):
    """
    Generate upload path specifically for product images
    """
    ext = filename.split('.')[-1].lower()
    unique_filename = f"{uuid.uuid4().hex}.{ext}"
    
    upload_dir = os.path.join(
        'uploads',
        'products',
        str(instance.retailer.id),
        datetime.now().strftime('%Y/%m')
    )
    
    return os.path.join(upload_dir, unique_filename)


def generate_retailer_image_path(instance, filename):
    """
    Generate upload path specifically for retailer images
    """
    ext = filename.split('.')[-1].lower()
    unique_filename = f"{uuid.uuid4().hex}.{ext}"
    
    upload_dir = os.path.join(
        'uploads',
        'retailers',
        str(instance.user.id),
        datetime.now().strftime('%Y/%m')
    )
    
    return os.path.join(upload_dir, unique_filename)


def generate_customer_image_path(instance, filename):
    """
    Generate upload path specifically for customer images
    """
    ext = filename.split('.')[-1].lower()
    unique_filename = f"{uuid.uuid4().hex}.{ext}"
    
    upload_dir = os.path.join(
        'uploads',
        'customers',
        str(instance.user.id),
        datetime.now().strftime('%Y/%m')
    )
    
    return os.path.join(upload_dir, unique_filename)


def compress_image(image_path, quality=85, max_size=(800, 800)):
    """
    Compress and resize image
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize image maintaining aspect ratio
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Save compressed image
            img.save(image_path, format='JPEG', quality=quality, optimize=True)
            
        return True
    except Exception as e:
        logger.error(f"Error compressing image: {str(e)}")
        return False


def validate_image_file(file):
    """
    Validate uploaded image file
    """
    # Check file size (5MB limit)
    if file.size > 5 * 1024 * 1024:
        return False, "File size cannot exceed 5MB"
    
    # Check file extension
    allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
    ext = file.name.split('.')[-1].lower()
    
    if ext not in allowed_extensions:
        return False, f"File type not supported. Allowed: {', '.join(allowed_extensions)}"
    
    return True, "File is valid"


def validate_document_file(file):
    """
    Validate uploaded document file
    """
    # Check file size (10MB limit)
    if file.size > 10 * 1024 * 1024:
        return False, "File size cannot exceed 10MB"
    
    # Check file extension
    allowed_extensions = ['pdf', 'doc', 'docx', 'xlsx', 'xls', 'csv']
    ext = file.name.split('.')[-1].lower()
    
    if ext not in allowed_extensions:
        return False, f"File type not supported. Allowed: {', '.join(allowed_extensions)}"
    
    return True, "File is valid"


def clean_filename(filename):
    """
    Clean filename by removing special characters
    """
    # Remove extension
    name, ext = os.path.splitext(filename)
    
    # Clean name
    clean_name = slugify(name)
    
    # Add extension back
    return f"{clean_name}{ext}"


def generate_unique_slug(model_class, title, slug_field='slug'):
    """
    Generate unique slug for a model
    """
    base_slug = slugify(title)
    slug = base_slug
    counter = 1
    
    while model_class.objects.filter(**{slug_field: slug}).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    
    return slug


def format_phone_number(phone):
    """
    Format phone number to standard format
    """
    # Remove all non-digit characters except +
    cleaned = ''.join(char for char in phone if char.isdigit() or char == '+')
    
    # Add country code if missing
    if not cleaned.startswith('+'):
        cleaned = '+91' + cleaned  # Default to India
    
    return cleaned


def validate_phone_number(phone):
    """
    Validate phone number format
    """
    cleaned = format_phone_number(phone)
    
    # Basic validation for Indian phone numbers
    if cleaned.startswith('+91'):
        number = cleaned[3:]
        if len(number) == 10 and number.isdigit():
            return True, cleaned
    
    return False, "Invalid phone number format"


def format_currency(amount):
    """
    Format amount as currency
    """
    return f"₹{amount:,.2f}"


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two coordinates using Haversine formula
    """
    import math
    
    # Convert latitude and longitude from degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in kilometers
    r = 6371
    
    return c * r


def generate_otp(length=6):
    """
    Generate random OTP
    """
    import random
    import string
    
    digits = string.digits
    return ''.join(random.choice(digits) for _ in range(length))


def mask_email(email):
    """
    Mask email address for privacy
    """
    if '@' not in email:
        return email
    
    local, domain = email.split('@')
    
    if len(local) <= 2:
        masked_local = local
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]
    
    return f"{masked_local}@{domain}"


def mask_phone(phone):
    """
    Mask phone number for privacy
    """
    if len(phone) <= 4:
        return phone
    
    return phone[:2] + '*' * (len(phone) - 4) + phone[-2:]


def get_client_ip(request):
    """
    Get client IP address from request
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request):
    """
    Get user agent from request
    """
    return request.META.get('HTTP_USER_AGENT', '')


def serialize_datetime(dt):
    """
    Serialize datetime to ISO format string
    """
    if dt:
        return dt.isoformat()
    return None


def paginate_queryset(queryset, page_size=20, page_number=1):
    """
    Paginate queryset manually
    """
    from django.core.paginator import Paginator
    
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page_number)
    
    return {
        'results': page_obj.object_list,
        'count': paginator.count,
        'num_pages': paginator.num_pages,
        'current_page': page_obj.number,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'next_page_number': page_obj.next_page_number() if page_obj.has_next() else None,
        'previous_page_number': page_obj.previous_page_number() if page_obj.has_previous() else None,
    }


def send_notification(user, title, message, notification_type='system'):
    """
    Send notification to user
    """
    try:
        from customers.models import CustomerNotification
        
        if user.user_type == 'customer':
            CustomerNotification.objects.create(
                customer=user,
                notification_type=notification_type,
                title=title,
                message=message
            )
            return True
    except Exception as e:
        logger.error(f"Error sending notification: {str(e)}")
        return False


def log_user_activity(user, action, details=None):
    """
    Log user activity
    """
    try:
        log_data = {
            'user_id': user.id,
            'username': user.username,
            'action': action,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"User Activity: {log_data}")
        return True
    except Exception as e:
        logger.error(f"Error logging user activity: {str(e)}")
        return False


def create_thumbnail(image_path, size=(200, 200)):
    """
    Create thumbnail from image
    """
    try:
        with Image.open(image_path) as img:
            img.thumbnail(size, Image.Resampling.LANCZOS)
            
            # Generate thumbnail path
            path_parts = image_path.split('.')
            thumbnail_path = f"{'.'.join(path_parts[:-1])}_thumb.{path_parts[-1]}"
            
            img.save(thumbnail_path, format='JPEG', quality=85)
            return thumbnail_path
    except Exception as e:
        logger.error(f"Error creating thumbnail: {str(e)}")
        return None


def cleanup_old_files(directory, days=30):
    """
    Clean up old files in directory
    """
    try:
        import os
        import time
        
        current_time = time.time()
        cutoff_time = current_time - (days * 24 * 60 * 60)
        
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.getmtime(file_path) < cutoff_time:
                    os.remove(file_path)
        
        return True
    except Exception as e:
        logger.error(f"Error cleaning up old files: {str(e)}")
        return False
