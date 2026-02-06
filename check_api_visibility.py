
import json
import os
import django
import sys
import urllib.request
import urllib.error

# Setup Django
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ordering_platform.settings')
django.setup()

from products.models import Product


print("Checking specific IDs 34 and 35 which were previously unavailable...")
p34 = Product.objects.filter(id=34).first()
if p34:
    print(f"Product 34: Active={p34.is_active}, Available={p34.is_available}")

p35 = Product.objects.filter(id=35).first()
if p35:
    print(f"Product 35: Active={p35.is_active}, Available={p35.is_available}")

# Find ANY unavailable active product
legacy_product = Product.objects.filter(is_active=True, is_available=False).last()
if not legacy_product:
    print("No legacy hidden products found in DB via filter(is_active=True, is_available=False).")
    # If P34/35 are available, then they were fixed somehow.
    # Use P35 for API test if it's available
    legacy_product = p35
else:
    print(f"Found Legacy Hidden Product: ID={legacy_product.id}")

url = f"http://127.0.0.1:8000/api/products/retailer/{legacy_product.retailer_id}/"
print(f"Calling Customer API: {url}")

try:
    with urllib.request.urlopen(url) as response:
        if response.status != 200:
            print(f"API Failed: {response.status}")
            sys.exit(1)
        


        data = json.loads(response.read().decode())
        found = False

        print(f"Debug: Data Type: {type(data)}")
        if isinstance(data, dict):
             print(f"Debug: Data Keys: {list(data.keys())}")
        
        # Safe extraction of results list
        if isinstance(data, dict) and 'results' in data:
            results = data['results']
        elif isinstance(data, list):
            results = data
        else:
            # Maybe it IS a single dict (detail view?) - unlikely for this endpoint
            results = [data] # Fallback
            
        print(f"Debug: Results type: {type(results)}")
        print(f"Debug: Results length: {len(results)}")

        if not results:
             print("No results found in response.")

        
        for p in results:
            if isinstance(p, dict):
                p_id = p.get('id')
            else:
                 # If it's not a dict, maybe it's a list of IDs or something unexpected?
                 print(f"Unexpected item format: {p}")
                 continue
                 
            if p_id == legacy_product.id:

                found = True
                print("!!! SURPRISE: Product FOUND in API Response!")
                print(json.dumps(p, indent=2))
                break
                
        if not found:
            print("XXX CONFIRMED: Product NOT found in API Response.")
            print("The backend filter 'is_available=True' is hiding it.")
            
except urllib.error.URLError as e:
    print(f"Error calling API: {e}")

