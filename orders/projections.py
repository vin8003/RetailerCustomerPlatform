from dataclasses import dataclass


@dataclass
class OrderProjectionAdapter:
    """Adapter over pre-annotated Order rows for serializer-friendly access."""
    order: object

    def __getattr__(self, item):
        return getattr(self.order, item)

    @property
    def items_count(self):
        return getattr(self.order, 'items_count_annotated', None)

    @property
    def refund_amount(self):
        return getattr(self.order, 'refund_amount_annotated', None)

    @property
    def net_amount(self):
        return getattr(self.order, 'net_amount_annotated', None)

    @property
    def is_returned(self):
        return getattr(self.order, 'is_returned_annotated', None)

    @property
    def customer_name(self):
        return getattr(self.order, 'customer_name_annotated', None)

    @property
    def has_customer_feedback(self):
        return getattr(self.order, 'has_feedback_annotated', None)

    @property
    def has_retailer_rating(self):
        return getattr(self.order, 'has_rating_annotated', None)

    @property
    def feedback_payload(self):
        if hasattr(self.order, 'feedback_overall_rating_annotated'):
            if self.order.feedback_overall_rating_annotated is None:
                return None
            return {
                'overall_rating': self.order.feedback_overall_rating_annotated,
                'comment': getattr(self.order, 'feedback_comment_annotated', None),
                'created_at': getattr(self.order, 'feedback_created_at_annotated', None),
            }
        return None
