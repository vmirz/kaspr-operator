import json
import kopf
import kubernetes_asyncio

_ALREADY_EXISTS = "alreadyexists"
_NOT_FOUND = "notfound"


def already_exists_error(ex: kubernetes_asyncio.client.ApiException) -> bool:
    if not isinstance(ex, kubernetes_asyncio.client.ApiException):
        return False
    else:
        err = json.loads(ex.body)
        return err.get("reason", "").lower() == _ALREADY_EXISTS

def not_found_error(ex: kubernetes_asyncio.client.ApiException) -> bool:
    if not isinstance(ex, kubernetes_asyncio.client.ApiException):
        return False
    else:
        err = json.loads(ex.body)
        return err.get("reason", "").lower() == _NOT_FOUND


def convert_api_exception(ex: kubernetes_asyncio.client.ApiException, permanent: bool = None):
    """
    Convert kubernetes ApiException to a Kopf-friendly exception.
    
    Args:
        ex: The ApiException to convert
        permanent: If True, raises PermanentError (won't retry). If False, raises TemporaryError (will retry).
                   If None, automatically determines based on status code.
    
    Raises:
        kopf.TemporaryError or kopf.PermanentError with serializable error details
    """
    if not isinstance(ex, kubernetes_asyncio.client.ApiException):
        raise ex
    
    # Extract error details from the exception
    error_msg = f"Kubernetes API error ({ex.status}): {ex.reason}"
    
    # Try to parse the body for more details
    try:
        if ex.body:
            body = json.loads(ex.body)
            if "message" in body:
                error_msg = f"{error_msg} - {body['message']}"
    except (json.JSONDecodeError, AttributeError):
        pass
    
    # Determine if this should be permanent based on status code
    # 4xx errors (except 408, 429) are typically permanent
    if permanent is None:
        is_permanent = 400 <= ex.status < 500 and ex.status not in [408, 429]
    else:
        is_permanent = permanent
    
    if is_permanent:
        raise kopf.PermanentError(error_msg)
    else:
        raise kopf.TemporaryError(error_msg, delay=30)


def get_labels_patch(diff):
    labels_patch = {}
    for op, field, old, new in diff:
        if "add" == op:
            if field:
                labels_patch[field[0]] = new
            else:
                for k, v in new.items():
                    labels_patch[k] = v
        elif "change" == op:
            labels_patch[field[0]] = new
        elif "remove" == op:
            if field:
                labels_patch[field[0]] = new
            else:
                for k, v in old.items():
                    labels_patch[k] = new
    return labels_patch
