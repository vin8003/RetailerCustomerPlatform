from django.apps import AppConfig


class ProductsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'products'

    def ready(self):
        import products.signals
        from products import views
        from products.search import smart_product_search
        views.smart_product_search = smart_product_search
