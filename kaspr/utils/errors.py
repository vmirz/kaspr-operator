import json
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
