from rest_framework.exceptions import ValidationError as DRFValidationError
from django.core.exceptions import ValidationError as DjangoValidationError

def format_exception(e):
    if isinstance(e, DRFValidationError):
        if isinstance(e.detail, dict):
            msgs = []
            for v in e.detail.values():
                if isinstance(v, list):
                    msgs.extend([str(item) for item in v])
                else:
                    msgs.append(str(v))
            return " ".join(msgs)
        elif isinstance(e.detail, list):
            return " ".join([str(item) for item in e.detail])
        return str(e.detail)
    elif isinstance(e, DjangoValidationError):
        if hasattr(e, 'message_dict') and e.message_dict:
            msgs = []
            for v in e.message_dict.values():
                if isinstance(v, list):
                    msgs.extend([str(item) for item in v])
                else:
                    msgs.append(str(v))
            return " ".join(msgs)
        elif hasattr(e, 'messages'):
            return " ".join([str(m) for m in e.messages])
    return str(e)
