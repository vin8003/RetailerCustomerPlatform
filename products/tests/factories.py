import factory
from factory.django import DjangoModelFactory
from ..models import Product, ProductCategory, ProductBrand, MasterProduct, ProductBatch
from decimal import Decimal

class ProductCategoryFactory(DjangoModelFactory):
    class Meta:
        model = ProductCategory
    
    name = factory.Sequence(lambda n: f"Category {n}")
    retailer = factory.SubFactory('retailers.tests.factories.RetailerProfileFactory')

class ProductBrandFactory(DjangoModelFactory):
    class Meta:
        model = ProductBrand
    
    name = factory.Sequence(lambda n: f"Brand {n}")

class MasterProductFactory(DjangoModelFactory):
    class Meta:
        model = MasterProduct
    
    barcode = factory.Sequence(lambda n: f"BARCODE{n}")
    name = factory.Sequence(lambda n: f"Master Product {n}")
    mrp = Decimal('100.00')

class ProductFactory(DjangoModelFactory):
    class Meta:
        model = Product
    
    retailer = factory.SubFactory('retailers.tests.factories.RetailerProfileFactory')
    name = factory.Sequence(lambda n: f"Product {n}")
    category = factory.SubFactory(ProductCategoryFactory)
    price = Decimal('90.00')
    original_price = Decimal('100.00')
    quantity = 10
    track_inventory = True
    is_active = True
    is_available = True

class ProductBatchFactory(DjangoModelFactory):
    class Meta:
        model = ProductBatch
    
    product = factory.SubFactory(ProductFactory)
    retailer = factory.SelfAttribute('product.retailer')
    batch_number = factory.Sequence(lambda n: f"BATCH-{n}")
    price = Decimal('90.00')
    original_price = Decimal('100.00')
    quantity = 10
    is_active = True

