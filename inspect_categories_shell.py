from products.models import ProductCategory
from retailers.models import RetailerCategory, RetailerProfile, RetailerCategoryMapping

print("--- Product Categories ---")
for cat in ProductCategory.objects.all()[:10]:
    print(f"ID: {cat.id}, Name: {cat.name}, Parent: {cat.parent_id}")

print("\n--- Retailer Categories ---")
for cat in RetailerCategory.objects.all()[:10]:
    print(f"ID: {cat.id}, Name: {cat.name}")

print("\n--- Retailer Mappings ---")
for mapping in RetailerCategoryMapping.objects.all()[:10]:
    print(f"Retailer: {mapping.retailer.shop_name}, Category: {mapping.category.name}, Primary: {mapping.is_primary}")
